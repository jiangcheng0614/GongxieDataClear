# -*- coding: utf-8 -*-
import os
import time
import json
import requests
import concurrent.futures
import threading
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

        self.cooldown_days = float(COOLDOWN_DAYS)  # 使用浮点数保持3.5天
        self.cooldown_seconds = self.cooldown_days * 86400
        self.cooldown_map = self._load_cooldown_map()  # { "article_size": last_ts }
        
        # 为每个群维护独立的计数器
        self.counter_group_1 = self._load_or_init_group_counter(1)  # ≤2
        self.counter_group_2 = self._load_or_init_group_counter(2)  # 3≤5
        self.counter_group_3 = self._load_or_init_group_counter(3)  # ≥6
        
        # 推送锁，防止并发重复推送
        self.push_lock = threading.Lock()
        # 正在推送的商品集合，防止重复推送
        self.pushing_products = set()
        # 计数器锁，防止并发时计数器冲突
        self.counter_lock = threading.Lock()
        
        # 连续失败计数器，用于检测登录过期
        self.consecutive_failures = 0
        self.max_failures_before_relogin = 3  # 连续失败3次后重新登录
        # 上次登录时间
        self.last_login_time = None
        # 登录有效期（秒），设为1小时，超过则主动刷新
        self.login_refresh_interval = 3600

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
        # 保留现有的群组计数器数据，避免覆盖
        if os.path.exists(self.counter_state_file):
            try:
                with open(self.counter_state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                state = {}
        else:
            state = {}
        state['date'] = self.current_date
        state['counter'] = self.product_counter
        try:
            self._fast_write_json(self.counter_state_file, state)
        except Exception as e:
            print(f"[warn] 写入 {os.path.basename(self.counter_state_file)} 失败：{e}")

    def _load_or_init_group_counter(self, group_num: int):
        """加载或初始化群组计数器"""
        today = self.current_date
        if os.path.exists(self.counter_state_file):
            try:
                with open(self.counter_state_file, 'r', encoding='utf-8') as f:
                    st = json.load(f)
                group_key = f'counter_group_{group_num}'
                if st.get('date') == today and isinstance(st.get(group_key), int) and st[group_key] >= 1:
                    return st[group_key]
            except Exception:
                pass
        self._save_group_counter(group_num, 1)
        return 1

    def _save_group_counter(self, group_num: int, value: int):
        """保存群组计数器"""
        today = self.current_date
        if os.path.exists(self.counter_state_file):
            try:
                with open(self.counter_state_file, 'r', encoding='utf-8') as f:
                    st = json.load(f)
            except Exception:
                st = {'date': today}
        else:
            st = {'date': today}
        
        st['date'] = today
        st[f'counter_group_{group_num}'] = value
        
        try:
            self._fast_write_json(self.counter_state_file, st)
        except Exception as e:
            print(f"[warn] 写入群组计数器失败：{e}")

    def _rollover_if_new_day(self):
        today = datetime.now().strftime('%Y-%m-%d')
        if today != self.current_date:
            print(f"[日期切换] {self.current_date} → {today}，重置所有计数器")
            self.current_date = today
            # 重置所有计数器为1
            self.product_counter = 1
            self.counter_group_1 = 1
            self.counter_group_2 = 1
            self.counter_group_3 = 1
            # 保存到文件
            state = {
                'date': today,
                'counter': 1,
                'counter_group_1': 1,
                'counter_group_2': 1,
                'counter_group_3': 1
            }
            try:
                self._fast_write_json(self.counter_state_file, state)
            except Exception as e:
                print(f"[warn] 重置计数器失败：{e}")

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

    # ====== 冷却（按尺码） ======
    def _cool_key_size(self, article_num: str, size: str, fallback_id: str) -> str:
        """生成冷却key：货号_尺码"""
        base = (article_num or "").strip()
        if base:
            return f"{base}_{size}"
        return f"{fallback_id}_{size}"

    def _is_cooled_size(self, key: str) -> bool:
        ts = self.cooldown_map.get(key)
        if not isinstance(ts, (int, float)):
            return False
        return (time.time() - float(ts)) < self.cooldown_seconds

    def _mark_cooled_size(self, key: str):
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

    # ===== 登录刷新 =====
    def _should_refresh_login(self):
        """检查是否需要刷新登录（超过1小时或连续失败多次）"""
        if self.last_login_time is None:
            return False
        elapsed = time.time() - self.last_login_time
        return elapsed > self.login_refresh_interval
    
    def _try_relogin(self):
        """尝试重新登录"""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔄 正在尝试重新登录...")
        if self.login_with_captcha(self.detail_processor):
            self.consecutive_failures = 0
            self.last_login_time = time.time()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✓ 重新登录成功")
            return True
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✗ 重新登录失败")
            return False

    # ===== 列表 =====
    def fetch_page(self, page_num, page_size=500):
        data = {'pageSize': str(page_size), 'pageNum': str(page_num),
                'orderByColumn': 'updateTime', 'isAsc': 'desc'}
        try:
            r = requests.post('https://www.gxkj123456.com/tgc/gxPc/seek/list',
                              cookies=self.cookies, headers=self.headers, data=data, timeout=10)
            if r.status_code != 200:
                print(f"[debug] fetch_page 状态码异常: {r.status_code}")
                return None
            result = r.json()
            if result.get('code') != 0:
                print(f"[debug] fetch_page 返回码异常: code={result.get('code')}, msg={result.get('msg', '')}")
                return None
            return result.get('rows', [])
        except Exception as e:
            print(f"[debug] fetch_page 异常: {e}")
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

                # ===== 新增检测（旧=0 → 新>0），需排除冷却中的尺码 =====
                def old0_newpos(s) -> bool:
                    old_c = int((old_full_snapshot.get(s) or {}).get('count', 0) or 0)
                    new_c = int((curr_full.get(s) or {}).get('count', 0) or 0)
                    return (s in kept_map) and (old_c <= 0 and new_c > 0)
                
                def is_size_cooled(s) -> bool:
                    """检查尺码是否在冷却期"""
                    size_key = self._cool_key_size(article_num, s, fallback_id=str(pid))
                    return self._is_cooled_size(size_key)

                # 排除冷却中的尺码
                newly_added_kept = [s for s in kept_all if old0_newpos(s) and not is_size_cooled(s)]
                has_new_size_order = len(newly_added_kept) > 0

                # ===== 获取所有要显示的尺码（包括价格超过范围的） =====
                # 所有允许的尺码（用于显示和计算群组）
                all_allowed_sizes = sorted(
                    [s for s in curr_full.keys() if self.detail_processor._size_allowed(s)],
                    key=self.detail_processor._size_sort_key
                )
                
                # ===== 按尺码检查冷却和筛选需要推送的尺码 =====
                # 对于 kept_map 中的尺码，检查冷却
                push_sizes_kept = []
                for s in kept_all:
                    size_key = self._cool_key_size(article_num, s, fallback_id=str(pid))
                    if not self._is_cooled_size(size_key):
                        push_sizes_kept.append(s)
                    else:
                        rem = self._cooldown_remaining_seconds(size_key)
                        if rem > 0:
                            print(f"  ⏳ 冷却中（货号={article_num} 尺码={s}）：剩余 {self._fmt_hms(rem)}")
                
                # 对于不在 kept_map 中的尺码（价格超过范围），不检查冷却，直接计入
                push_sizes_other = [s for s in all_allowed_sizes if s not in kept_all]
                
                # 合并所有要推送的尺码
                push_sizes = push_sizes_kept + push_sizes_other

                # ===== 是否推送 =====
                need_push = False
                # 只在以下情况推送：
                # 1. 新增商品且有未冷却的符合条件的尺码
                # 2. 有尺码的订单数从0变为>0（0→正数）且未冷却
                if change_type.startswith('🆕') and push_sizes_kept:
                    # 新增商品也检查冷却，只有未冷却的尺码才推送
                    need_push = True
                elif has_new_size_order:
                    need_push = True
                # 注意：不再因为"有未冷却的尺码"就推送，避免无变化时重复推送

                # 未触发：仅更新历史
                if not need_push:
                    target['detail_data'] = detail_result
                    target['size_price_counts'] = kept_map
                    target['full_size_price_counts'] = curr_full
                    self.detail_processor.update_product_history(target, target['size_price_counts'], curr_full)
                    self.save_initial_data()
                    continue

                # 触发推送：只推送未冷却的尺码（kept_map中的）
                filtered_kept_map = {s: kept_map[s] for s in push_sizes_kept if s in kept_map}
                detail_for_output = dict(detail_result)
                detail_for_output['size_price_counts'] = filtered_kept_map
                detail_for_output['size_price_counts_full'] = curr_full

                # 根据所有要显示的尺码数量确定群组和计数器（包括价格超过范围和冷却中的）
                # 使用 all_allowed_sizes 而不是 push_sizes，因为群组分配应该基于所有显示的尺码
                size_count = len(all_allowed_sizes)
                
                # 使用锁保护计数器操作，防止并发冲突
                with self.counter_lock:
                    if size_count <= 2:
                        group_num = 1
                        next_no = self.counter_group_1
                        self.counter_group_1 += 1
                        self._save_group_counter(1, self.counter_group_1)
                    elif size_count <= 5:
                        group_num = 2
                        next_no = self.counter_group_2
                        self.counter_group_2 += 1
                        self._save_group_counter(2, self.counter_group_2)
                    else:  # >= 6
                        group_num = 3
                        next_no = self.counter_group_3
                        self.counter_group_3 += 1
                        self._save_group_counter(3, self.counter_group_3)

                formatted_output, img_url = self.detail_processor.format_product_output(
                    target, detail_for_output, history_view, next_no, change_type, group_num
                )

                if formatted_output:
                    # 使用推送锁和集合防止重复推送
                    # 使用 pid 作为唯一标识，而不是 next_no（因为 next_no 可能不同）
                    push_key = f"{article_num}_{pid}" if article_num else str(pid)
                    with self.push_lock:
                        if push_key in self.pushing_products:
                            print(f"⚠ 商品 {article_num or pid} 正在推送中，跳过重复推送")
                            # 回滚计数器（使用计数器锁）
                            with self.counter_lock:
                                if group_num == 1:
                                    self.counter_group_1 -= 1
                                    self._save_group_counter(1, self.counter_group_1)
                                elif group_num == 2:
                                    self.counter_group_2 -= 1
                                    self._save_group_counter(2, self.counter_group_2)
                                else:
                                    self.counter_group_3 -= 1
                                    self._save_group_counter(3, self.counter_group_3)
                            continue
                        self.pushing_products.add(push_key)
                    
                    try:
                        print(f"\n📦 处理商品 {next_no} (群组{group_num}, 尺码数{size_count}):")
                        print(formatted_output)
                        self.write_to_output_file(formatted_output)

                        ok = self.wechat_bot.send_product_to_bot(formatted_output, img_url, group_num)
                        if ok:
                            print(f"✓ 商品 {next_no} 推送成功")
                            processed += 1
                            # 按尺码冷却（只对 kept_map 中的尺码进行冷却）
                            for s in push_sizes_kept:
                                size_key = self._cool_key_size(article_num, s, fallback_id=str(pid))
                                self._mark_cooled_size(size_key)
                            # 只有推送成功才更新历史数据
                            target['detail_data'] = detail_result
                            target['size_price_counts'] = kept_map
                            target['full_size_price_counts'] = curr_full
                            self.detail_processor.update_product_history(target, target['size_price_counts'], curr_full)
                            self.save_initial_data()
                        else:
                            print(f"✗ 商品 {next_no} 推送失败")
                            # 推送失败时回滚计数器，保持编号连续（使用计数器锁）
                            with self.counter_lock:
                                if group_num == 1:
                                    self.counter_group_1 -= 1
                                    self._save_group_counter(1, self.counter_group_1)
                                elif group_num == 2:
                                    self.counter_group_2 -= 1
                                    self._save_group_counter(2, self.counter_group_2)
                                else:
                                    self.counter_group_3 -= 1
                                    self._save_group_counter(3, self.counter_group_3)
                    finally:
                        # 推送完成后从集合中移除
                        with self.push_lock:
                            self.pushing_products.discard(push_key)
                time.sleep(1)

        if processed == 0:
            print("  没有符合条件的变化")

    # ===== 主循环 =====
    def monitor_products(self, check_interval=1):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始监控商品数据...")
        if not self.login_with_captcha(self.detail_processor):
            print("登录失败，无法继续监控")
            return
        self.last_login_time = time.time()  # 记录登录时间

        while True:
            try:
                self._rollover_if_new_day()
                
                # 检查是否需要主动刷新登录（超过1小时）
                if self._should_refresh_login():
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏰ 登录已超过1小时，主动刷新...")
                    self._try_relogin()
                
                t0 = time.time()
                all_new_products = []
                page_num = 1

                first = self.fetch_page(page_num, page_size=500)
                if not first:
                    self.consecutive_failures += 1
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 获取第一页失败 (连续失败 {self.consecutive_failures} 次)")
                    
                    # 连续失败多次，尝试重新登录
                    if self.consecutive_failures >= self.max_failures_before_relogin:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⚠ 连续失败 {self.consecutive_failures} 次，可能是登录过期")
                        if self._try_relogin():
                            # 重新登录成功，立即重试获取
                            first = self.fetch_page(page_num, page_size=500)
                            if first:
                                self.consecutive_failures = 0
                                all_new_products.extend(first)
                            else:
                                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 重新登录后仍获取失败，等待下次检查")
                                time.sleep(check_interval)
                                continue
                        else:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待下次检查...")
                            time.sleep(check_interval)
                            continue
                    else:
                        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 等待下次检查...")
                        time.sleep(check_interval)
                        continue
                else:
                    self.consecutive_failures = 0  # 成功后重置失败计数
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
