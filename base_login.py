import os
import json
import base64
import random
import requests

class BaseLogin:
    def __init__(self):
        self.cookies = {
            'JSESSIONID': '0824ef5c-ba10-4c77-8d01-9405395b3022',
        }
        self.headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://www.gxkj123456.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'sec-ch-ua': '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }

    def base64_api(self, uname, pwd, img, typeid):
        with open(img, 'rb') as f:
            base64_data = base64.b64encode(f.read())
            b64 = base64_data.decode()
        data = {"username": uname, "password": pwd, "typeid": typeid, "image": b64}
        result = json.loads(requests.post("http://api.ttshitu.com/predict", json=data).text)
        if result['success']:
            return result["data"]["result"]
        else:
            return result["message"]

    def login_with_captcha(self, detail_processor=None):
        session = requests.Session()
        session.cookies.update({
            'username-m': '13266769662',
            'password-m': 'Imzl1107',
            'isvehicle-m': 'true',
            'JSESSIONID': '29079ff1-43f4-4b28-905f-194a4d3c3417',
            '_ati': '4765820810259',
        })
        login_headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://www.gxkj123456.com',
            'Referer': 'https://www.gxkj123456.com/tgc/login',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest',
            'groupId': '0',
            'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
        captcha_headers = login_headers.copy()
        captcha_headers.update({
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
        })
        params = {'type': 'math','s': str(random.random())}
        try:
            captcha_response = session.get('https://www.gxkj123456.com/tgc/captcha/captchaImage', params=params, headers=captcha_headers, timeout=5)
            captcha_path = 'captcha_math.jpg'
            with open(captcha_path, 'wb') as f:
                f.write(captcha_response.content)
            captcha_result = self.base64_api(uname='FOURFIRE', pwd='Imzl1107', img=captcha_path, typeid=11)
            if os.path.exists(captcha_path):
                os.remove(captcha_path)
            print(f"识别到的验证码结果: {captcha_result}")
            login_data = {'username': '13266769662','password': 'Imzl1107','validateCode': captcha_result,'rememberMe': 'false'}
            login_response = session.post('https://www.gxkj123456.com/tgc/login', headers=login_headers, data=login_data, timeout=5)
            if login_response.status_code == 200:
                jsessionid = login_response.cookies.get('JSESSIONID')
                if jsessionid:
                    self.cookies['JSESSIONID'] = jsessionid
                    if detail_processor:
                        detail_processor.update_cookies(jsessionid)
                    print(f"登录成功，获取到JSESSIONID: {jsessionid}")
                    return True
                else:
                    print("登录失败：未获取到JSESSIONID")
                    return False
            else:
                print(f"登录失败，状态码: {login_response.status_code}")
                return False
        except Exception as e:
            print(f"登录过程发生异常: {str(e)}")
            return False
