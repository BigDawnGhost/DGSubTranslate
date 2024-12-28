import time
import os
from DrissionPage import Chromium,ChromiumOptions
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


def compare_and_process_files(file1, file2, output_file, max_workers=20):
    def process_subtitle(index, match1, match2):
        begin1, end1, text1 = match1
        _, _, text2 = match2

        if text1 == text2:
            text2 = translate(text2)

        return index, f"{begin1} --> {end1}\n{text2}\n\n"

    # 打开两个文件并读取内容
    with open(file1, 'r', encoding='utf-8') as f1, open(file2, 'r', encoding='utf-8') as f2:
        srt_text1 = f1.read()
        srt_text2 = f2.read()

    # 正则表达式用于匹配字幕块
    pattern = r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n"

    matches1 = re.findall(pattern, srt_text1, re.S)
    matches2 = re.findall(pattern, srt_text2, re.S)

    # 确保两个文件的字幕数量相同
    if len(matches1) != len(matches2):
        raise ValueError("两个文件的字幕数量不同，无法比较处理。")

    # 结果存储列表
    result = [None] * len(matches1)

    # 使用线程池处理字幕块
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交任务
        futures = {
            executor.submit(process_subtitle, i, match1, match2): i
            for i, (match1, match2) in enumerate(zip(matches1, matches2))
        }

        # 使用tqdm显示进度条
        with tqdm(total=len(matches1), desc="正在检查", unit="block") as pbar:
            for future in as_completed(futures):
                index, processed_block = future.result()
                result[index] = processed_block
                pbar.update(1)
    os.remove(file2)
    # 将结果写入输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(result)

def process_blocks_multithread(blocks, max_workers=10):
    result = [None] * len(blocks)  # 预分配结果列表

    # 定义一个包装函数供线程使用
    def process_block(index, block):
        return index, translate(block)+'\n\n\n'

    # 创建线程池并使用tqdm显示进度条
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务，并记录索引
        future_to_index = {executor.submit(process_block, i, block): i for i, block in enumerate(blocks)}

        # 使用tqdm跟踪进度
        with tqdm(total=len(blocks), desc="处理中", unit="block") as pbar:
            for future in as_completed(future_to_index):
                index, translated_block = future.result()
                result[index] = translated_block  # 按索引存储到结果列表
                pbar.update(1)

    return result


def translate(text):
    while True:
        try:
            tab = chromium.new_tab()
            tab.get('https://www.deepl.com/')
            tab.ele(
                r'c:#textareasContainer > div.rounded-es-inherit.relative.min-h-\[240px\].min-w-0.md\:min-h-\[clamp\(250px\,50vh\,557px\)\].mobile\:min-h-0.mobile\:portrait\:max-h-\[calc\(\(100vh-61px-1px-64px\)\/2\)\] > section > div > div.relative.flex-1.rounded-inherit.mobile\:min-h-0 > d-textarea > div:nth-child(1)').input(
                text)
            time.sleep(5)
            text = tab.ele(
                r'c:#textareasContainer > div.rounded-ee-inherit.relative.min-h-\[240px\].min-w-0.md\:min-h-\[clamp\(250px\,50vh\,557px\)\].mobile\:min-h-0.mobile\:flex-1.mobile\:portrait\:max-h-\[calc\(\(100vh-61px-1px-64px\)\/2\)\].max-\[768px\]\:min-h-\[375px\] > section > div.rounded-inherit.mobile\:min-h-0.relative.flex.flex-1.flex-col > d-textarea > div').text
            tab.close()

            return text.replace('\n\n', '\n')
        except:
            print('restart')
            continue


def accumulate_by_length(lst, limit=1400):
    blocks = []
    current_str = ""
    current_length = 0

    for string in lst:
        # 获取当前字符串的长度
        string_length = len(string)

        # 尝试将当前字符串加到当前累积字符串中
        if current_length + string_length > limit:
            # 如果超过了限制，先保存当前的累积字符串
            blocks.append(current_str)
            # 将当前字符串作为新的累积字符串的起点
            current_str = string
            current_length = string_length
        else:
            # 否则继续累加
            current_str += string
            current_length += string_length

    # 最后将剩余的累积字符串添加到结果中
    blocks.append(current_str)
    return blocks

def main(file):
    # 读取 SRT 文件内容
    with open(file, 'r', encoding='utf-8') as f:
        srt_text = f.read()
    text_list = []
    # 正则表达式匹配字幕
    pattern = r"(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n"
    matches = re.findall(pattern,srt_text, re.S)
    for match in matches:
        begin, end, text = match
        text_list.append(text + '\n\n\n')

    blocks = accumulate_by_length(text_list)
    result = process_blocks_multithread(blocks)
    text_list = ''.join(result).strip().split('\n\n\n')
    file_m = 'm.srt'
    for i in range(len(matches)):
        try:
            begin, end, text = matches[i]
            translated_text = text_list[i]
            content_now = (f"{i + 1}\n{begin} --> {end}\n{translated_text}\n\n")
            with open(file_m, 'a') as f:
                f.write(content_now)
        except:
            pass
    compare_and_process_files(file, file_m, f'{file} zh.srt')


if __name__ == '__main__':
    chromium = Chromium()
    chromium.set.cookies.clear()
    tab = chromium.get_tab()
    print('开始初始化')
    tab.get('https://www.deepl.com/')
    time.sleep(4)
    tab.ele('c:#cookieBanner > div > span > button').click()
    time.sleep(2)
    print('初始化成功')
    file = input('输入字幕文件路径：')
    main(file)
    print('运行结束')
    chromium.quit()

