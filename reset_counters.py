# -*- coding: utf-8 -*-
"""
重置所有群组的NO.计数器
"""
import os
import json
from datetime import datetime

def reset_all_counters():
    """重置所有群组计数器为1"""
    counter_file = 'daily_counter.json'
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 读取当前计数器
    if os.path.exists(counter_file):
        try:
            with open(counter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取计数器文件失败：{e}")
            data = {}
    else:
        data = {}
    
    # 重置所有计数器
    data['date'] = today
    data['counter'] = 1
    data['counter_group_1'] = 1
    data['counter_group_2'] = 1
    data['counter_group_3'] = 1
    
    # 保存
    try:
        with open(counter_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ 所有计数器已重置为1")
        print(f"  群组1: {data['counter_group_1']}")
        print(f"  群组2: {data['counter_group_2']}")
        print(f"  群组3: {data['counter_group_3']}")
    except Exception as e:
        print(f"保存计数器文件失败：{e}")

def reset_group_counter(group_num: int):
    """重置指定群组的计数器为1"""
    counter_file = 'daily_counter.json'
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 读取当前计数器
    if os.path.exists(counter_file):
        try:
            with open(counter_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"读取计数器文件失败：{e}")
            data = {}
    else:
        data = {}
    
    # 重置指定群组计数器
    data['date'] = today
    group_key = f'counter_group_{group_num}'
    data[group_key] = 1
    
    # 保存
    try:
        with open(counter_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ 群组{group_num}的计数器已重置为1")
    except Exception as e:
        print(f"保存计数器文件失败：{e}")

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        # 重置指定群组
        try:
            group_num = int(sys.argv[1])
            if group_num in [1, 2, 3]:
                reset_group_counter(group_num)
            else:
                print("错误：群组编号必须是1、2或3")
        except ValueError:
            print("错误：群组编号必须是数字")
    else:
        # 重置所有群组
        reset_all_counters()

