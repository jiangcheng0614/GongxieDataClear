import os
import base64
import hashlib
from datetime import datetime
import requests
import re

class WeChatBot:
    def __init__(self, webhook_urls=None):
        # 群组1：≤2个尺码
        self.webhook_urls_group_1 = [
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bfe9d59e-079b-4d46-ac81-4a09046c251e',
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=48e65b2d-d616-4f3c-a43c-30d484d4350d",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=141f6d09-2f11-48d2-a208-a123b273cc75"
        ]
        # 群组2：3≤5个尺码
        self.webhook_urls_group_2 = [
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=83eb44d6-63b3-4e4d-914a-92d5dc34aade",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=afb4a142-2c57-42dc-859e-d21a09104af3",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=b9d2d25b-7e1e-4bd6-a31b-f3e1f1bd4f55"
        ]
        # 群组3：≥6个尺码
        self.webhook_urls_group_3 = webhook_urls or [
            'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=01e859e5-ac15-4493-820c-58724a442ae8',
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=5ed2a770-8298-436b-acc8-063921a585f2",
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=c86d9c6e-3dcb-43cb-a094-edc98f0a1c3f"
        ]
        self.current_bot_index_group_1 = 0
        self.current_bot_index_group_2 = 0
        self.current_bot_index_group_3 = 0

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

    def send_product_to_bot(self, content, img_url, group_num=1):
        """
        根据群组发送消息
        :param content: 消息内容
        :param img_url: 图片URL
        :param group_num: 群组编号 (1: ≤2, 2: 3≤5, 3: ≥6)
        """
        # 根据群组选择webhook列表
        if group_num == 1:
            webhook_urls = self.webhook_urls_group_1
            current_index = self.current_bot_index_group_1
        elif group_num == 2:
            webhook_urls = self.webhook_urls_group_2
            current_index = self.current_bot_index_group_2
        else:  # group_num == 3
            webhook_urls = self.webhook_urls_group_3
            current_index = self.current_bot_index_group_3

        if not webhook_urls:
            return False

        webhook_url = webhook_urls[current_index]
        path = f"temp_image_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"  # 添加微秒避免文件名冲突

        downloaded = None
        try:
            downloaded = self.download_image(img_url, path)
            
            # 如果图片下载失败，只发送文本
            if not downloaded:
                ok_text = self.send_text_message(content, webhook_url)
                if ok_text:
                    # 只有文本发送成功才更新索引
                    if group_num == 1:
                        self.current_bot_index_group_1 = (self.current_bot_index_group_1 + 1) % len(webhook_urls)
                    elif group_num == 2:
                        self.current_bot_index_group_2 = (self.current_bot_index_group_2 + 1) % len(webhook_urls)
                    else:
                        self.current_bot_index_group_3 = (self.current_bot_index_group_3 + 1) % len(webhook_urls)
                return ok_text

            # 先发送图片
            ok_img = self.send_image_message(downloaded, webhook_url)
            if not ok_img:
                # 图片发送失败，尝试只发送文本
                ok_text = self.send_text_message(content, webhook_url)
                # 文本发送成功也需要更新索引
                if ok_text:
                    if group_num == 1:
                        self.current_bot_index_group_1 = (self.current_bot_index_group_1 + 1) % len(webhook_urls)
                    elif group_num == 2:
                        self.current_bot_index_group_2 = (self.current_bot_index_group_2 + 1) % len(webhook_urls)
                    else:
                        self.current_bot_index_group_3 = (self.current_bot_index_group_3 + 1) % len(webhook_urls)
                return ok_text
            
            # 图片发送成功，再发送文本
            ok_text = self.send_text_message(content, webhook_url)
            
            # 只有图片和文本都发送成功才更新索引
            if ok_text:
                if group_num == 1:
                    self.current_bot_index_group_1 = (self.current_bot_index_group_1 + 1) % len(webhook_urls)
                elif group_num == 2:
                    self.current_bot_index_group_2 = (self.current_bot_index_group_2 + 1) % len(webhook_urls)
                else:
                    self.current_bot_index_group_3 = (self.current_bot_index_group_3 + 1) % len(webhook_urls)
            
            return ok_text
        except Exception as e:
            print(f"[推送错误] 群组{group_num}: {str(e)}")
            return False
        finally:
            # 清理临时文件
            try:
                if downloaded and os.path.exists(downloaded):
                    os.remove(downloaded)
            except:
                pass