# -*- coding: utf-8 -*-
import json
import requests
import concurrent.futures
from datetime import datetime
from base_login import BaseLogin
from detail_processor import DetailProcessor

class DataInitializer(BaseLogin):
    def __init__(self):
        super().__init__()
        self.detail_processor = DetailProcessor()
        self.data_file = 'initial_products_data.json'
        self.max_workers = 10

    def fetch_all_products(self):
        all_products = []
        page_num = 1
        page_size = 500
        while True:
            products = self.fetch_page(page_num, page_size)
            if not products or len(products) == 0:
                break
            all_products.extend(products)
            if len(products) < page_size:
                break
            page_num += 1
        return all_products

    def fetch_page(self, page_num, page_size):
        data = {
            'pageSize': str(page_size),
            'pageNum': str(page_num),
            'orderByColumn': 'updateTime',
            'isAsc': 'desc'
        }
        try:
            r = requests.post(
                'https://www.gxkj123456.com/tgc/gxPc/seek/list',
                cookies=self.cookies, headers=self.headers, data=data, timeout=10
            )
            if r.status_code != 200:
                return None
            result = r.json()
            if result.get('code') != 0:
                return None
            return result.get('rows', [])
        except Exception:
            return None

    def _fetch_and_attach_detail(self, product):
        """初始化阶段也按‘逐尺码请求→聚合’的逻辑保存完整快照，以便后续人数对比"""
        try:
            d = self.detail_processor.fetch_and_process_detail(product)
            if d:
                product['detail_data'] = d
                product['last_checked'] = datetime.now().isoformat()
                product['size_price_counts'] = d.get('size_price_counts', {})
                product['full_size_price_counts'] = d.get('size_price_counts_full', {})
                return product
        except Exception:
            pass
        return None

    def initialize_all_data(self):
        if not self.login_with_captcha(self.detail_processor):
            return
        all_products = self.fetch_all_products()
        if not all_products:
            return
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            fut = {ex.submit(self._fetch_and_attach_detail, p): p for p in all_products}
            for _ in concurrent.futures.as_completed(fut):
                pass
        self.save_data(all_products)

    def save_data(self, products):
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
