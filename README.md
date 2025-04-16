# RSSTranslate-AI
A Python script that translates RSS feeds into specified languages using AI and generates new RSS subscription links. 
Python 脚本，使用 AI 技术将原始 RSS 源内容翻译成指定语言，并生成新的可订阅 RSS 链接。

## 功能特点

- 获取原始 RSS 源内容
- 使用 OpenAI API 翻译 RSS 条目(标题、描述、内容)
- 通过分块处理长文本，提高翻译质量
- 实现翻译缓存，避免重复翻译
- 生成包含翻译内容的新 RSS 源文件
- 提供可订阅的翻译后 RSS 链接
- 提供强大的错误处理和重试机制

## 使用方法
- 提前在服务器装好Python3 环境，确保pip已安装，并安装所需库
pip3 install feedparser feedgen openai python-dotenv pytz
然后下载代码放到自己服务器上，
- 使用的时候先修改config.json文件和.env文件
把config.json里的注释全删除，默认模型是gpt-4.1-nano，实测用来翻译够用了，不满意也可以换你想用的模型，
以及其他需要改的地方都在config.json里的注释都写了。

### 配置参数说明

- `output_directory`: 存储翻译后 RSS 文件的目录
- `cache_file`: 存储翻译缓存的文件
- `log_file`: 操作日志文件
- `max_items`: 每个 Feed 处理的最大条目数
- `openai_model`: 用于翻译的 OpenAI 模型
- `system_prompt`: 指导翻译模型的提示语
- `sources`: 要翻译的 RSS 源数组
  - `original_url`: 原始 RSS 源的 URL
  - `output_file`: 翻译后 Feed 的文件名
  - `title`: Feed 的标题(可选)
  
### PY脚本配置

首次运行后会自动创建translate.log和translation_cache.json ，
默认分割字符数是10000，在78行和179行，改的话动这2行的数字，因为输入字符数多了以后nano容易翻译不准确，故设置的保守了点。
`api_timeout`: API 调用超时时间(秒), 默认120，也是设置的很保守，改的话在176行，这个是翻译等待的时间，并不是每次翻译都要等120秒才进行下一篇文章的翻译，
如果10秒就出了翻译结果，那么脚本会立刻进行下一篇文章的翻译，如果120秒还没出结果，就会进入重试，一共会重试3次，都失败的话就使用原文，然后进行下一篇文章的翻译。
重试次数max_retries的设置在185行和222行，默认是3次。
API有速率限制，添加短暂延迟避免触发限制，延迟时间time.sleep的设置在197行和238行，默认3秒。

### 运行脚本
先cd到脚本所在文件夹，然后
python3 translate_rss.py

## 功能详细介绍

### 翻译缓存

脚本使用原始文本的 SHA256 哈希值缓存翻译结果，避免重复的 API 调用。这提高了性能并减少了 API 成本。

### 长文本分块处理

对于长文章（超过10000字符，设置方法见PY脚本配置），脚本会自动将内容分割成较小的块（10000字符）进行翻译，然后合并结果，保持更好的翻译质量。

### 错误处理

包含 API 失败时的重试机制和无法完成翻译时的优雅降级处理。

## 注意事项

- 翻译质量取决于所使用的 AI 模型
- API 使用会根据你的 OpenAI 计划产生费用
- 翻译大型 Feed 时请考虑 API 速率限制

## 许可证

GPL-3.0 license

