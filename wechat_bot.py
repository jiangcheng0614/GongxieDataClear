import os
import base64
import hashlib
from datetime import datetime
import requests
import re

class WeChatBot:
    def __init__(self, webhook_urls=None):
        self.webhook_urls = webhook_urls or [
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a12cd9ae-c9d0-4833-95f5-9fdb7217afa7',
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=aed9de32-bc31-4dcc-a2bf-4ba095c12c72',
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=f68517d2-d13c-4b61-8a50-341505305e78'
        ]
        self.current_bot_index = 0
        self.webhook_urls_lower_3 = ["https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=df5fb23e-09af-4143-a7d0-f6684442d215",
                                     "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=c6f1f0c0-e3af-4d83-ae3a-f06d6b9ca162",
                                     "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=a3125e03-7efc-460b-a7ef-e73c1bcf6e91"
                                     ]
        self.current_bot_index_lower_3 = 0

    def download_image(self, img_url, save_path='temp_image.jpg'):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36','Referer': 'https://www.gxkj123456.com/'}
            r = requests.get(img_url, headers=headers, timeout=5)
            if r.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(r.content)
                return save_path
            return None
        except Exception:
            return None

    def send_text_message(self, content, webhook_url):
        payload = {"msgtype": "text", "text": {"content": content}}
        try:
            r = requests.post(webhook_url, json=payload, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def send_image_message(self, image_path, webhook_url):
        if not os.path.exists(image_path):
            return False
        try:
            with open(image_path, 'rb') as f:
                data = f.read()
            md5 = hashlib.md5(data).hexdigest()
            b64 = base64.b64encode(data).decode('utf-8')
            if len(b64) > 2 * 1024 * 1024:
                return False
            payload = {"msgtype": "image", "image": {"base64": b64, "md5": md5}}
            r = requests.post(webhook_url, json=payload, timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def send_product_to_bot(self, content, img_url):
        if not self.webhook_urls:
            return False
        webhook_url = self.webhook_urls[self.current_bot_index]
        path = f"temp_image_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"

        # 判断发送哪个群,3个
        if self.match_index(content) <= 4:
            webhook_url = self.webhook_urls_lower_3[self.current_bot_index_lower_3]

        downloaded = self.download_image(img_url, path)
        if not downloaded:
            return self.send_text_message(content, webhook_url)

        try:
            ok_img = self.send_image_message(downloaded, webhook_url)
            if not ok_img:
                return False
            ok_text = self.send_text_message(content, webhook_url)
            if self.match_index(content) <= 4:
                self.current_bot_index_lower_3 = (self.current_bot_index_lower_3 + 1) % len(self.webhook_urls_lower_3)
            else:
                self.current_bot_index = (self.current_bot_index + 1) % len(self.webhook_urls)
            return ok_text
        except Exception:
            return False
        finally:
            try:
                if downloaded and os.path.exists(downloaded):
                    os.remove(downloaded)
            except:
                pass

    def match_index(self, text):
        ''' 匹配文本中的订单个数
        :params text: str, 文本内容
        '''
        matches = re.findall(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)
        return len(matches)
