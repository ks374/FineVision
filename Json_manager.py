# json_manager.py
import json
import os

def read_json(file_path):
    """
    读取指定路径的 JSON 文件内容。
    如果文件不存在或损坏，返回一个空字典。
    """
    if not os.path.exists(file_path):
        return {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"[警告] 文件 {file_path} 格式损坏或为空，已作为空数据处理。")
        return {}
    except Exception as e:
        print(f"[错误] 读取 {file_path} 时发生未知错误: {e}")
        return {}

def update_json(file_path, key, data):
    """
    更新或添加 JSON 文件中的某个顶层 key。
    采用“读出 -> 修改 -> 写入”的模式，防止覆盖原有其他数据。
    """
    # 1. 读取现有数据
    file_data = read_json(file_path)
    
    # 2. 更新指定字段
    file_data[key] = data
    
    # 3. 安全写回文件
    try:
        # 先写到一个临时文件中（防止写入中途断电或崩溃导致原文件损坏）
        temp_path = file_path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(file_data, f, indent=4, ensure_ascii=False)
        
        # 写入成功后，替换原文件 (原子操作)
        os.replace(temp_path, file_path)
        return True
    except Exception as e:
        print(f"[错误] 写入 {file_path} 时失败: {e}")
        return False