# -*- coding: utf-8 -*-
import re
import time
import requests
import urllib.parse
import concurrent.futures
from bs4 import BeautifulSoup

EXCLUDED_BRANDS = [
    'under armour','hoka','saucony','salomon','puma','lining','new balance','ugg',
    'asics','reebok','anta','361°','fila','pop mart','crocs','on昂跑','birkenstock',
    'arcteryx始祖鸟','mlb','onitsuka tiger','dr.martens','ecco','timberland',
    'michael kors','特步','迪桑特','mizuno','under armour','斯凯奇','yonex尤尼斯',
    'p-6000','pro 4','nike sabrina','adidas originals samba','air zoom vomero 5',
    'a.e. 1','nike ja 1','g.t. cut 3','adizero evo sl','nike ja 3','nike ja 2','skechers','vans','converse','louis vuitton','北面','迪卡侬']

ALLOWED_SIZES = ['35.5','36','36.5','37','37.5','38','38.5','39','39.5',
                 '40','40.5','41','41.5','42','42.5','43','43.5','44','44.5','45',]

PRICE_MIN = 270.0
PRICE_MAX = 1800.0
REQ_TIMEOUT = 8
SIZE_WORKERS = 1
MAX_RETRIES = 3
RETRY_BACKOFF = 0.6


class DetailProcessor:
    def __init__(self):
        self.cookies = {'JSESSIONID': 'replace-me'}
        self.detail_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Referer': 'https://www.gxkj123456.com/tgc/gxPc/seek/list',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
        }
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=128, pool_maxsize=256)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def update_cookies(self, jsessionid: str):
        self.cookies['JSESSIONID'] = jsessionid

    def fetch_and_process_detail(self, product_data: dict):
        return self._fetch_by_iter_sizes(product_data)

    # ===== 规则 =====
    def _should_skip_brand(self, title: str) -> bool:
        if not title:
            return False
        tl = title.lower()
        return any(b in tl for b in EXCLUDED_BRANDS)

    def _size_allowed(self, size: str) -> bool:
        return True if not ALLOWED_SIZES else (str(size) in ALLOWED_SIZES)

    def _in_price_range_or_zero(self, price_str: str) -> bool:
        # "未出价"也当作有效尺码
        if price_str == '未出价' or price_str.strip() == '未出价':
            return True
        try:
            p = float(price_str)
        except Exception:
            return False
        if p == 0.0:
            return True
        return PRICE_MIN <= p <= PRICE_MAX

    # ===== 解析 =====
    def _parse_people_and_time(self, html: str):
        soup = BeautifulSoup(html, 'html.parser')
        txt = soup.get_text(" ", strip=True)

        m = re.search(r'(\d+)\s*人', txt)
        if m:
            try:
                people = int(m.group(1))
            except Exception:
                people = 0
        else:
            tables = soup.find_all('table')
            table = tables[1] if len(tables) > 1 else soup
            people = len(table.find_all('a', string=re.compile(r'联系TA')))

        all_times = re.findall(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)', txt)
        latest_time = sorted(all_times)[-1] if all_times else ""
        return people, latest_time

    def _extract_hand_price(self, html: str) -> str:
        patterns = [
            r'3\.5\s*到手：\s*(\d+(?:\.\d+)?)',
            r'到手价?：\s*(\d+(?:\.\d+)?)',
            r'到手\s*(\d+(?:\.\d+)?)',
        ]
        for pat in patterns:
            m = re.search(pat, html, flags=re.IGNORECASE)
            if m:
                return m.group(1)
        if re.search(r'3\.5\s*到手：\s*0(?:\.0+)?', html):
            return '0.0'
        return '未出价'

    # ===== 单尺码请求（带轻量重试） =====
    def _fetch_one_size(self, pid: str, size: str, ptype: str = '0'):
        params = {'pid': pid, 'type': ptype, 'size': str(size)}
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.session.get(
                    'https://www.gxkj123456.com/tgc/gxPc/seek/work/seeks',
                    params=params, cookies=self.cookies, headers=self.detail_headers,
                    timeout=REQ_TIMEOUT, allow_redirects=True
                )
                if r.status_code != 200 or not r.text:
                    raise RuntimeError(f"http_{r.status_code}")
                price_str = self._extract_hand_price(r.text)
                people_cnt, latest_time = self._parse_people_and_time(r.text)
                return price_str, people_cnt, latest_time
            except Exception:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
                    continue
                return '未出价', 0, ""

    def _fetch_by_iter_sizes(self, product_data: dict):
        title = (product_data.get('title') or '').strip()
        if self._should_skip_brand(title):
            return None

        pid   = str(product_data.get('productId') or '')
        ptype = str(product_data.get('type', '0') or '0')
        sizes = list(dict.fromkeys([str(s) for s in (product_data.get('sizes') or [])]))

        article_num = (product_data.get('articleNum') or '').strip()
        img_url     = (product_data.get('logoUrl') or '').strip()
        update_time = (product_data.get('updateTime') or '').strip()

        full_snapshot = {}
        filtered      = {}

        def _job(s):
            if not s:
                return str(s), ('未出价', 0, '')
            return str(s), self._fetch_one_size(pid, s, ptype)

        if sizes:
            with concurrent.futures.ThreadPoolExecutor(max_workers=SIZE_WORKERS) as ex:
                for s, (price_str, people_cnt, latest_time) in ex.map(_job, sizes):
                    full_snapshot[str(s)] = {
                        'price': price_str, 'count': int(people_cnt), 'time': latest_time
                    }
                    if self._size_allowed(s) and people_cnt > 0 and self._in_price_range_or_zero(price_str):
                        filtered[str(s)] = {
                            'price': price_str, 'count': int(people_cnt), 'time': latest_time
                        }

        return {
            'hand_price': '',
            'title': title,
            'article_num': article_num,
            'img_url': img_url,
            'size_price_counts': filtered,
            'size_price_counts_full': full_snapshot,
            'update_time': update_time
        }

    def _size_sort_key(self, s):
        try:
            return (0, float(s))
        except Exception:
            return (1, s)

    def kept_sizes_in_range(self, current_price_counts):
        kept = []
        if not current_price_counts:
            return kept
        for s, info in current_price_counts.items():
            price_str = str(info.get('price', '未出价'))
            c = int(info.get('count', 0) or 0)
            
            # 检查尺码是否允许
            if ALLOWED_SIZES and s not in ALLOWED_SIZES:
                continue
            
            # 检查订单数是否大于0
            if c <= 0:
                continue
            
            # 检查价格是否在范围内（与 _in_price_range_or_zero 保持一致）
            if self._in_price_range_or_zero(price_str):
                kept.append(s)
        return kept
    def format_product_output(self, product_data, detail_data, product_history, product_number, change_type, group_num=1):
        title       = (detail_data.get('title') or '').strip()
        article_num = (detail_data.get('article_num') or '').strip()
        img_url     = detail_data.get('img_url', '')

        cpc      = detail_data.get('size_price_counts') or {}
        full_now = detail_data.get('size_price_counts_full') or {}
        old_full = product_history.get('full_size_price_counts', {}) or {}

        all_allowed_sizes = sorted(
            [s for s in full_now.keys() if self._size_allowed(s)],
            key=self._size_sort_key
        )
        if not all_allowed_sizes:
            return None, img_url

        def gf(q: str) -> str:
            return f"https://www.goofish.com/search?q={urllib.parse.quote_plus(q.strip())}"

        size_blocks = []
        prices_for_range = []  # 用于计算价格区间的有效价格列表

        for s in all_allowed_sizes:
            in_kept = (s in cpc)
            cur = cpc.get(s, full_now.get(s, {}) or {})
            price_str = str(cur.get('price', '未出价'))
            try:
                cc = int(cur.get('count', 0) or 0)
            except Exception:
                cc = 0
            stime = str(cur.get('time', '') or '')
            oc = int((old_full.get(s) or {}).get('count', 0) or 0)
            
            # 历史价格补全：如果当前价格为0或未知，使用上次采集的3.5价格
            old_price_info = old_full.get(s, {}) or {}
            old_price_str = str(old_price_info.get('price', '未出价') or '未出价')
            is_old_price = False
            
            # 判断当前价格是否为0或未知
            # 先检查是否为"未出价"字符串，再尝试转换为数字
            if price_str == '未出价' or price_str.strip() == '未出价':
                is_zero_or_unknown = True
            else:
                try:
                    current_price_val = float(price_str)
                    is_zero_or_unknown = (current_price_val == 0.0)
                except (ValueError, TypeError):
                    is_zero_or_unknown = True
            
            # 如果当前价格为0或未知，且历史价格有效，则使用历史价格
            if is_zero_or_unknown and old_price_str and old_price_str != '未出价':
                try:
                    old_price_val = float(old_price_str)
                    if old_price_val > 0:
                        price_str = old_price_str
                        is_old_price = True
                except (ValueError, TypeError):
                    pass
            
            # 订单变化标记：0→1 表示订单变化
            mark = ""
            if in_kept:
                # 0→1 为订单变化
                if oc <= 0 and cc > 0:
                    mark = "🆕"
                else:
                    mark = "📌"
            
            # 显示格式：标记【尺码】价格(旧订单数→新订单数) ⏱最新订单时间
            # 如果是旧价格，添加标记
            display_price = price_str
            if is_old_price:
                display_price = f"{price_str}(旧价格)"
            
            size_blocks.append(f"{mark}【{s}】{display_price}({oc}→{cc})  ⏱{stime}")

            qkey = (article_num if article_num else title).strip()
            if qkey:
                size_blocks.append(gf(f"{qkey} {s}"))

            # 收集有效价格用于计算价格区间（仅收集有订单且价格有效的尺码）
            if in_kept and cc > 0:
                try:
                    # 使用实际价格（可能是历史价格）进行计算
                    price_val = float(price_str)
                    # 只收集非零价格用于区间计算
                    if price_val > 0:
                        prices_for_range.append(price_val)
                except Exception:
                    pass

        # 优化价格区间计算：最低价格 = 最低价格的0.3倍（不低于150），最高价格 = 最高价格 - 30
        price_line = ""
        if prices_for_range:
            try:
                min_price = min(prices_for_range)
                max_price = max(prices_for_range)
                
                # 最低价格 = 最低价格的0.3倍，但不低于150
                calculated_min = max(min_price * 0.3, 150.0)
                # 最高价格 = 最高价格 - 30
                calculated_max = max_price - 30.0
                
                # 确保最低价格不超过最高价格
                if calculated_min > calculated_max:
                    calculated_min = calculated_max
                
                price_line = f"价格区间：【{int(calculated_min)}-{int(calculated_max)}】\n"
            except Exception:
                price_line = ""

        kept_list = sorted(list(cpc.keys()), key=self._size_sort_key)
        ks_str = "、".join(kept_list) if kept_list else ""

        lines = []
        lines.append(f"【NO.{product_number}】(群组{group_num})")
        lines.extend(size_blocks)
        lines.append("")
        title_with_art = f"{title}{article_num}" if article_num else title
        lines.append(title_with_art)
        if article_num:
            lines.append(gf(article_num))
        if price_line:
            lines.append(price_line.rstrip())
        if ks_str:
            lines.append(f"尺码符合要求范围【{ks_str}】")
        if title:
            lines.append(gf(title))

        out = "\n".join(lines).rstrip() + "\n"
        return out, img_url

    def update_product_history(self, product_history, current_price_counts, full_snapshot=None):
        kept_sizes = self.kept_sizes_in_range(current_price_counts)
        product_history['kept_sizes'] = kept_sizes
        product_history['size_price_counts'] = {
            s: current_price_counts.get(s, {}) for s in kept_sizes if s in (current_price_counts or {})
        }
        product_history['full_size_price_counts'] = dict(full_snapshot or {})

    def filter_valid_sizes(self, sizes):
        return list(sizes) if sizes else []
