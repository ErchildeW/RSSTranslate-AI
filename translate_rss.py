import feedparser
from feedgen.feed import FeedGenerator
import os
import json
import datetime
import pytz
import logging
from dotenv import load_dotenv
import time
import sys
import hashlib
import requests

# 全局 logger 实例
logger = logging.getLogger("rss_translator")

# 加载环境变量和API密钥
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")

# 确保API基础URL没有尾部斜杠
if api_base.endswith('/'):
    api_base = api_base.rstrip('/')

print(f"使用API基础URL: {api_base}")

if not api_key:
    print("错误: OpenAI API密钥未设置！请在.env文件中添加OPENAI_API_KEY", file=sys.stderr)
    sys.exit(1)

def setup_logging(config):
    """根据配置设置日志记录"""
    log_file_path = config.get("log_file", "translate.log")
    log_dir = os.path.dirname(log_file_path)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir)
        except Exception as e:
            print(f"创建日志目录失败: {log_dir}, 错误: {e}", file=sys.stderr)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file_path, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def load_config():
    """加载配置文件"""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"错误: 加载配置文件失败: {e}", file=sys.stderr)
        sys.exit(1)

def load_cache(cache_file):
    """加载翻译缓存"""
    try:
        if os.path.exists(cache_file):
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
    return {}

def save_cache(cache, cache_file):
    """保存翻译缓存"""
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"保存缓存失败: {e}")

def split_text(text, max_length=10000):
    """将长文本分割成更小的片段"""
    # 如果文本小于最大长度，直接返回
    if len(text) <= max_length:
        return [text]
    
    # 尝试按段落分割
    paragraphs = text.split('\n\n')
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        # 如果段落本身超过最大长度，进一步分割
        if len(para) > max_length:
            # 简单地按最大长度切割
            for i in range(0, len(para), max_length):
                chunks.append(para[i:i+max_length])
            continue
            
        # 如果添加此段落会超过最大长度，先保存当前块
        if len(current_chunk) + len(para) + 2 > max_length:  # +2 for '\n\n'
            chunks.append(current_chunk)
            current_chunk = para
        else:
            # 否则添加到当前块
            if current_chunk:
                current_chunk += '\n\n' + para
            else:
                current_chunk = para
    
    # 不要忘记最后一个块
    if current_chunk:
        chunks.append(current_chunk)
        
    return chunks

def translate_api_call(text, model_name, system_prompt, timeout=120):
    """单次API调用来翻译文本"""
    # 设置请求头部和数据
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"翻译以下文本:\n\n{text}"}
        ],
        "temperature": 0.3,
        "max_tokens": 4096
    }

    # 确保URL路径正确
    url = f"{api_base}/chat/completions"
    logger.debug(f"请求URL: {url}")
    
    # 尝试API调用，增加超时时间
    try:
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        
        # 检查状态码
        if response.status_code != 200:
            raise Exception(f"API返回错误状态码: {response.status_code}, 内容: {response.text}")
        
        # 解析JSON响应
        response_json = response.json()
        logger.debug(f"API响应: {json.dumps(response_json, ensure_ascii=False)[:200]}...")
        
        # 提取翻译结果
        translation = response_json["choices"][0]["message"]["content"].strip()
        return translation
        
    except Exception as e:
        logger.error(f"API调用失败: {e}")
        raise

def translate_text(text, cache, cache_file, config):
    """使用API翻译文本，支持长文本分块处理"""
    if not text or text.strip() == "":
        return ""

    # 使用SHA256哈希值作为缓存键
    cache_key = hashlib.sha256(text.encode('utf-8')).hexdigest()

    # 尝试从缓存加载
    if cache_key in cache:
        logger.debug(f"缓存命中: {cache_key[:10]}...")
        return cache[cache_key]

    logger.info(f"翻译文本 (长度: {len(text)} 字符)")

    # 从配置中获取模型名称和系统提示
    model_name = config.get("openai_model", "gpt-4.1-nano")
    system_prompt = config.get("system_prompt", "你是一个专业的中英翻译。请将以下英文文本（或者中文文本）翻译成流畅、自然的中文。无论我的输入是英文还是中文，都必须用中文返回给我，不要对内容进行思考或者总结，只需要把翻译的结果发给我，并保留原文的格式，包括HTML标签。")
    
    # 获取超时设置，默认120秒
    timeout = config.get("api_timeout", 120)

    # 处理长文本
    MAX_CHUNK_SIZE = 10000  # 每个块的最大字符数
    
    try:
        # 如果文本长度适中，直接翻译
        if len(text) <= MAX_CHUNK_SIZE:
            # 添加重试机制
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                try:
                    translation = translate_api_call(text, model_name, system_prompt, timeout)
                    
                    # 存入缓存
                    cache[cache_key] = translation
                    save_cache(cache, cache_file)
                    
                    # API有速率限制，添加短暂延迟避免触发限制
                    time.sleep(3)
                    
                    return translation
                    
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"翻译失败，尝试重试 ({retry_count}/{max_retries}): {e}")
                    time.sleep(2 ** retry_count)  # 指数退避等待
            
            # 所有重试都失败
            logger.error(f"翻译多次失败，返回原文")
            return f"[翻译失败] {text}"
        
        # 对于长文本，分块处理
        else:
            logger.info(f"文本过长 ({len(text)} 字符)，分块处理")
            chunks = split_text(text, MAX_CHUNK_SIZE)
            logger.info(f"文本已分为 {len(chunks)} 个块")
            
            translated_chunks = []
            
            for i, chunk in enumerate(chunks):
                logger.info(f"翻译第 {i+1}/{len(chunks)} 块 (长度: {len(chunk)} 字符)")
                
                # 对每个块使用重试机制
                max_retries = 3
                retry_count = 0
                chunk_translated = False
                
                while retry_count < max_retries and not chunk_translated:
                    try:
                        # 增加特殊提示表明这是分块翻译
                        chunk_system_prompt = system_prompt
                        if len(chunks) > 1:
                            chunk_system_prompt += f" 这是第 {i+1}/{len(chunks)} 部分的文本，请保持翻译风格一致。"
                        
                        translation = translate_api_call(chunk, model_name, chunk_system_prompt, timeout)
                        translated_chunks.append(translation)
                        chunk_translated = True
                        
                        # API有速率限制，添加短暂延迟避免触发限制
                        time.sleep(3)  # 分块翻译间隔稍长一些
                        
                    except Exception as e:
                        retry_count += 1
                        logger.warning(f"块 {i+1} 翻译失败，尝试重试 ({retry_count}/{max_retries}): {e}")
                        time.sleep(2 ** retry_count)  # 指数退避等待
                
                # 如果当前块翻译失败
                if not chunk_translated:
                    logger.error(f"块 {i+1} 翻译多次失败，使用原文")
                    translated_chunks.append(f"[翻译失败] {chunk}")
            
            # 合并翻译结果
            full_translation = "\n\n".join(translated_chunks)
            
            # 存入缓存
            cache[cache_key] = full_translation
            save_cache(cache, cache_file)
            
            return full_translation

    except Exception as e:
        logger.error(f"翻译出错: {e}")
        return f"[翻译错误] {text}"

# process_feed 函数保持不变
def process_feed(source_config, cache, cache_file, max_items, config):
    """处理单个RSS源并生成翻译后的Feed"""
    original_url = source_config["original_url"]
    output_file = source_config["output_file"]
    feed_title = source_config.get("title", "未命名Feed")

    logger.info(f"处理RSS源: {feed_title} ({original_url})")

    try:
        # 解析原始Feed
        feed = feedparser.parse(original_url)

        if feed.bozo and hasattr(feed, 'bozo_exception'):
            logger.warning(f"解析Feed时出现警告: {feed.bozo_exception}")

        # 创建新的Feed生成器
        fg = FeedGenerator()
        fg.title(f"中文翻译: {feed.feed.get('title', feed_title)}")
        fg.link(href=feed.feed.get('link', original_url), rel='alternate')
        fg.description(f"自动翻译的 {feed.feed.get('title', feed_title)}")
        fg.language('zh-CN')

        if 'image' in feed.feed and hasattr(feed.feed.image, 'href'):
            fg.logo(feed.feed.image.href)

        entries_to_process = feed.entries[:max_items]
        logger.info(f"处理 {len(entries_to_process)} 个条目")

        for entry in entries_to_process:
            fe = fg.add_entry()

            original_title = entry.get('title', '')
            translated_title = translate_text(original_title, cache, cache_file, config)
            fe.title(translated_title)

            original_content = ""
            if 'content' in entry and entry.content:
                original_content = entry.content[0].value
            elif 'summary' in entry:
                original_content = entry.summary
            elif 'description' in entry:
                original_content = entry.description

            translated_content = translate_text(original_content, cache, cache_file, config)
            fe.content(translated_content, type='html')

            fe.link(href=entry.get('link', ''))
            fe.guid(entry.get('id', entry.get('link', '')), permalink=True)

            pub_date = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_date = datetime.datetime(*entry.published_parsed[:6])
                if pub_date.tzinfo is None or pub_date.tzinfo.utcoffset(pub_date) is None:
                    try:
                        pub_date = pytz.utc.localize(pub_date)
                    except Exception: pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                 pub_date = datetime.datetime(*entry.updated_parsed[:6])
                 if pub_date.tzinfo is None or pub_date.tzinfo.utcoffset(pub_date) is None:
                     try:
                         pub_date = pytz.utc.localize(pub_date)
                     except Exception: pass

            if pub_date:
                 fe.pubDate(pub_date)
            else:
                 fe.pubDate(datetime.datetime.now(pytz.utc))

        output_path = os.path.join(config["output_directory"], output_file)

        fg.rss_file(output_path, pretty=True, encoding='UTF-8')
        logger.info(f"成功生成翻译后的Feed: {output_path}")

        return True

    except Exception as e:
        logger.error(f"处理Feed '{feed_title}'时出错: {e}")
        return False

def main():
    # 加载配置
    try:
        global config
        config = load_config()
    except Exception as e:
        print(f"关键错误: 无法加载配置文件 config.json: {e}", file=sys.stderr)
        sys.exit(1)

    # 配置日志记录
    setup_logging(config)

    logger.info("开始RSS翻译任务")
    logger.info(f"使用API基础URL: {api_base}")

    try:
        # 检查输出目录是否存在
        if not os.path.exists(config["output_directory"]):
            logger.warning(f"输出目录不存在: {config['output_directory']}")
            try:
                os.makedirs(config["output_directory"])
                logger.info(f"已创建输出目录: {config['output_directory']}")
            except Exception as e:
                logger.error(f"创建输出目录失败: {e}")
                sys.exit(1)

        # 加载缓存
        cache_file = config.get("cache_file", "translation_cache.json")
        cache = load_cache(cache_file)

        # 处理每个RSS源
        max_items = config.get("max_items", 15)
        success_count = 0

        for source in config["sources"]:
            if process_feed(source, cache, cache_file, max_items, config):
                success_count += 1

        logger.info(f"RSS翻译任务完成。成功处理 {success_count}/{len(config['sources'])} 个源。")

    except Exception as e:
        logger.error(f"RSS翻译任务执行失败: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
