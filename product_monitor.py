# -*- coding: utf-8 -*-
import os
import time
import json
import requests
import concurrent.futures
from datetime import datetime
from base_login import BaseLogin
from detail_processor import DetailProcessor
from wechat_bot import WeChatBot

COOLDOWN_DAYS = 3.5
COOLDOWN_FILE = 'cooldown_state.json'

class ProductMonitor(BaseLogin):
    def __init__(self):
        super().__init__()
        self.BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        self.initial_data_file = os.path.join(self.BASE_DIR, 'initial_products_data.json')
        self.output_file = os.path.join(self.BASE_DIR, 'products_output.txt')
        self.counter_state_file = os.path.join(self.BASE_DIR, 'daily_counter.json')
        self.cooldown_file = os.path.join(self.BASE_DIR, COOLDOWN_FILE)

        self.detail_processor = DetailProcessor()
        self.wechat_bot = WeChatBot()
        self.products_data = self.load_initial_data()

        self.current_date = datetime.now().strftime('%Y-%m-%d')
        self.product_counter = self._load_or_init_daily_counter()

        self.max_workers = 8

        self.cooldown_days = int(COOLDOWN_DAYS)
        self.cooldown_seconds = self.cooldown_days * 86400
        self.cooldown_map = self._load_cooldown_map()  # { "article_or_id": last_ts }

    # ====== 简易 I/O ======
    def _fast_write_json(self, path: str, obj):
        path = os.path.abspath(path)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

    def _load_or_init_daily_counter(self):
        today = self.current_date
        if os.path.exists(self.counter_state_file):
            try:
                with open(self.counter_state_file, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                if st.get('date') == today and isinstance(st.get('counter'), int) and st['counter'] >= 1:
                    return st['counter']
            except Exception:
                pass
        self._save_daily_counter(1)
        return 1

    def _save_daily_counter(self, value=None):
        if value is not None:
            self.product_counter = value
        state = {'date': self.current_date, 'counter': self.product_counter}
        try:
            self._fast_write_json(self.counter_state_file, state)
        except Exception as e:
            print(f"[warn] 写入 {os.path.basename(self.counter_state_file)} 失败：{e}")

    def _rollover_if_new_day(self):
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.current_date:
            self.current_date = today
            self._save_daily_counter(1)

    # ====== 业务 I/O ======
    def load_initial_data(self):
        if os.path.exists(self.initial_data_file):
            try:
                with open(self.initial_data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[warn] 读取 {os.path.basename(self.initial_data_file)} 失败：{e}")
                return []
        return []

    def save_initial_data(self):
        try:
            self._fast_write_json(self.initial_data_file, self.products_data)
        except Exception as e:
            print(f"[warn] 写入 {os.path.basename(self.initial_data_file)} 失败：{e}")

    def write_to_output_file(self, content):
        try:
            with open(self.output_file, 'a', encoding='utf-8') as f:
                f.write(content + '\n' + '=' * 80 + '\n\n')
        except Exception as e:
            print(f"[warn] 写入 {os.path.basename(self.output_file)} 失败：{e}")

    # ====== 冷却（整款） ======
    def _cool_key_product(self, article_num: str, fallback_id: str) -> str:
        base = (article_num or "").strip()
        return base if base else str(fallback_id)

    def _is_cooled_product(self, key: str) -> bool:
        ts = self.cooldown_map.get(key)
        if not isinstance(ts, (int, float)):
            return False
        return (time.time() - float(ts)) < self.cooldown_seconds

    def _mark_cooled_product(self, key: str):
        self.cooldown_map[key] = time.time()
        self._save_cooldown_map()

    def _cooldown_remaining_seconds(self, key: str) -> int:
        ts = self.cooldown_map.get(key)
        if not isinstance(ts, (int, float)):
            return 0
        elapsed = time.time() - float(ts)
        rem = int(self.cooldown_seconds - elapsed)
        return rem if rem > 0 else 0

    def _fmt_hms(self, seconds: int) -> str:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _load_cooldown_map(self):
        if os.path.exists(self.cooldown_file):
            try:
                with open(self.cooldown_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[warn] 读取 {os.path.basename(self.cooldown_file)} 失败：{e}")
                return {}
        return {}

    def _save_cooldown_map(self):
        try:
            self._fast_write_json(self.cooldown_file, self.cooldown_map)
        except Exception as e:
            print(f"[warn] 写入 {os.path.basename(self.cooldown_file)} 失败：{e}")

    # ===== 列表 =====
    def fetch_page(self, page_num, page_size=500):
        data = {'pageSize': str(page_size), 'pageNum': str(page_num),
                'orderByColumn': 'updateTime', 'isAsc': 'desc'}
        try:
            r = requests.post('https://www.gxkj123456.com/tgc/gxPc/seek/list',
                              cookies=self.cookies, headers=self.headers, data=data, timeout=10)
            if r.status_code != 200:
                return None
            result = r.json()
            if result.get('code') != 0:
                return None
            return result.get('rows', [])
        except Exception:
            return None

    def detect_changes(self, new_products):
        new_items, updated_items, unchanged_items = [], [], []
        existing_ids = {p['id']: p for p in self.products_data}
        for product in new_products:
            pid = product['id']
            if pid not in existing_ids:
                new_items.append(product)
                product['size_price_counts'] = {}
                product['full_size_price_counts'] = {}
                product['last_checked'] = datetime.now().isoformat()
                self.products_data.append(product)
            else:
                old = existing_ids[pid]
                if product.get('updateTime') != old.get('updateTime'):
                    updated_items.append({'old': old, 'new': product})
                    old.update(product)
                    old['last_checked'] = datetime.now().isoformat()
                else:
                    unchanged_items.append(product)
        return new_items, updated_items, unchanged_items

    def _find_or_attach_ref(self, product):
        for p in self.products_data:
            if p['id'] == product['id']:
                return p
        self.products_data.append(product)
        return product

    def process_products_streaming(self, products, change_type):
        if not products:
            return

        id_to_ref = {p['id']: self._find_or_attach_ref(p) for p in products}

        processed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_id = {ex.submit(self.detail_processor.fetch_and_process_detail, p): p['id'] for p in products}
            for fut in concurrent.futures.as_completed(future_to_id):
                pid = future_to_id[fut]
                target = id_to_ref.get(pid)
                if not target:
                    continue

                try:
                    detail_result = fut.result()
                except Exception as e:
                    print(f"[detail error] product {pid}: {e}")
                    continue
                if not detail_result:
                    continue

                article_num = detail_result.get('article_num', '') or target.get('articleNum', '') or ''
                curr_full = detail_result.get('size_price_counts_full', {}) or {}
                kept_map = detail_result.get('size_price_counts', {}) or {}  # 白名单 + 人数>0 + (价在区间或=0)
                kept_all = sorted(list(kept_map.keys()), key=self.detail_processor._size_sort_key)

                # —— 老快照 —— #
                old_full_snapshot = target.get('full_size_price_counts', {}) or {}
                old_kept_sizes = target.get('kept_sizes', []) or []
                history_view = {'full_size_price_counts': old_full_snapshot, 'kept_sizes': old_kept_sizes}

                # 商品级冷却key
                prod_key = self._cool_key_product(article_num, fallback_id=str(pid))

                # ===== 新增检测（旧=0 → 新>0） =====
                def old0_newpos(s) -> bool:
                    old_c = int((old_full_snapshot.get(s) or {}).get('count', 0) or 0)
                    new_c = int((curr_full.get(s) or {}).get('count', 0) or 0)
                    return (s in kept_map) and (old_c <= 0 and new_c > 0)

                newly_added_kept = [s for s in kept_all if old0_newpos(s)]
                has_new_size_order = len(newly_added_kept) > 0

                # ===== 单零价保护（仅对“新增”生效） =====
                # 允许的全部白名单尺码（判断是否“整款单码”）
                allowed_all_sizes = [s for s in curr_full.keys() if self.detail_processor._size_allowed(s)]
                is_single_size_product = (len(allowed_all_sizes) == 1)

                single_zero_guard = False
                if (change_type.startswith('🆕') or has_new_size_order) and len(newly_added_kept) == 1:
                    s0 = newly_added_kept[0]
                    pstr = str((kept_map.get(s0) or {}).get('price', '')).strip()
                    try:
                        pv = float(pstr)
                        is_zero_price = (pv == 0.0)
                    except Exception:
                        is_zero_price = False
                    if (not is_single_size_product) and is_zero_price:
                        single_zero_guard = True

                # ===== 是否推送 =====
                need_push = False
                # 新增优先；仅在新增路径应用 single_zero_guard
                if (change_type.startswith('🆕') and kept_all) or has_new_size_order:
                    if not single_zero_guard:
                        need_push = True
                # 非新增路径（例如更新）不受单零价保护影响
                elif kept_all and not self._is_cooled_product(prod_key):
                    need_push = True

                # 未触发：仅更新历史并（若在冷却）打印剩余冷却
                if not need_push:
                    if kept_all and self._is_cooled_product(prod_key):
                        rem = self._cooldown_remaining_seconds(prod_key)
                        if rem > 0:
                            print(f"  ⏳ 冷却中（商品id={pid} 货号={article_num}）：剩余 {self._fmt_hms(rem)}")
                    target['detail_data'] = detail_result
                    target['size_price_counts'] = kept_map
                    target['full_size_price_counts'] = curr_full
                    self.detail_processor.update_product_history(target, target['size_price_counts'], curr_full)
                    self.save_initial_data()
                    continue

                # 触发推送：整款打印（白名单全部尺码；仅 kept 打标，未出价不打标）
                detail_for_output = dict(detail_result)
                detail_for_output['size_price_counts'] = kept_map
                detail_for_output['size_price_counts_full'] = curr_full

                next_no = self.product_counter
                formatted_output, img_url = self.detail_processor.format_product_output(
                    target, detail_for_output, history_view, next_no, change_type
                )

                # 回写历史
                target['detail_data'] = detail_result
                target['size_price_counts'] = kept_map
                target['full_size_price_counts'] = curr_full

                if formatted_output:
                    print(f"\n📦 处理商品 {next_no}:")
                    print(formatted_output)
                    self.write_to_output_file(formatted_output)

                    ok = self.wechat_bot.send_product_to_bot(formatted_output, img_url)
                    if ok:
                        print(f"✓ 商品 {next_no} 推送成功")
                        processed += 1
                        # 整款冷却
                        self._mark_cooled_product(prod_key)
                    else:
                        print(f"✗ 商品 {next_no} 推送失败")

                    self.product_counter += 1
                    self._save_daily_counter()

                # 更新历史并落盘
                self.detail_processor.update_product_history(target, target['size_price_counts'], curr_full)
                self.save_initial_data()
                time.sleep(1)

        if processed == 0:
            print("  没有符合条件的变化")

    # ===== 主循环 =====
    def monitor_products(self, check_interval=1):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监控商品数据...")
        if not self.login_with_captcha(self.detail_processor):
            print("登录失败，无法继续监控")
            return

        while True:
            try:
                self._rollover_if_new_day()
                t0 = time.time()
                all_new_products = []
                page_num = 1

                first = self.fetch_page(page_num, page_size=500)
                if not first:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 获取第一页失败，等待下次检查")
                    time.sleep(check_interval)
                    continue
                all_new_products.extend(first)

                while True:
                    page_num += 1
                    page_products = self.fetch_page(page_num, page_size=500)
                    if not page_products or len(page_products) == 0:
                        break
                    all_new_products.extend(page_products)

                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 共获取 {len(all_new_products)} 个商品")

                new_items, updated_items, _ = self.detect_changes(all_new_products)

                if new_items:
                    print(f"发现 {len(new_items)} 个新商品")
                    self.process_products_streaming(new_items, "🆕新增")

                if updated_items:
                    print(f"发现 {len(updated_items)} 个更新商品")
                    updated_products = [i['new'] for i in updated_items]
                    self.process_products_streaming(updated_products, "📌更新")

                self.save_initial_data()
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 本次监控耗时: {time.time() - t0:.2f}秒")
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待 {check_interval} 秒后进行下一次检查...")
                time.sleep(check_interval)
            except Exception as e:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 监控过程发生异常: {str(e)}")
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待 {check_interval} 秒后重试...")
                time.sleep(check_interval)
