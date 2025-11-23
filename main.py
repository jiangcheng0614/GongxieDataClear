import os
from data_initializer import DataInitializer
from product_monitor import ProductMonitor

def main():
    initial_data_file = 'initial_products_data.json'
    if not os.path.exists(initial_data_file):
        print("检测到初始数据文件不存在，开始初始化数据...")
        initializer = DataInitializer()
        initializer.initialize_all_data()
        print("数据初始化完成！")
    else:
        print("检测到初始数据文件已存在，跳过初始化...")
    print("开始监控商品变化...")
    monitor = ProductMonitor()
    monitor.monitor_products(check_interval=5)

if __name__ == '__main__':
    main()
