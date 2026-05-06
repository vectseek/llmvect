# -*- coding: utf-8 -*-
"""
中国大模型配置 - 仅限国产大模型
"""

# 大模型厂商配置
LLM_PROVIDERS = {
    # ==================== 第一梯队：巨头系 ====================
    "alibaba": {
        "name": "阿里巴巴",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long", "qwen2.5-max"],
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "docs": "https://help.aliyun.com/zh/dashscope/",
        "icon": "🔷",
        "color": "#FF6A00"
    },
    "baidu": {
        "name": "百度",
        "models": ["ernie-4.0-8k", "ernie-3.5-8k", "ernie-speed-8k", "ernie-4.5", "ernie-x1"],
        "api_base": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat",
        "api_key_env": "BAIDU_API_KEY",
        "docs": "https://cloud.baidu.com/doc/WENXINWORKSHOP/index.html",
        "icon": "🔵",
        "color": "#2932E1",
        "special": "baidu",
        "auth_type": "baidu"
    },
    "tencent": {
        "name": "腾讯",
        "models": ["hunyuan-lite", "hunyuan-standard", "hunyuan-pro", "hunyuan-turbo-s", "hunyuan-t1"],
        "api_base": "https://api.hunyuan.cloud.tencent.com/v1",
        "api_key_env": "TENCENT_API_KEY",
        "docs": "https://cloud.tencent.com/document/product/1729",
        "icon": "🟢",
        "color": "#07C160"
    },
    "byteDance": {
        "name": "字节跳动",
        "models": ["doubao-seed-2-0-pro-260215"],
        "api_base": "https://ark.cn-beijing.volces.com/api/v3/responses",
        "api_key_env": "DOUBAO_API_KEY",
        "docs": "https://www.volcengine.com/docs/82379",
        "icon": "⚫",
        "color": "#000000"
    },
    "xfyun": {
        "name": "科大讯飞",
        "models": ["spark-lite", "spark-general", "spark-pro", "spark-max", "spark-x1"],
        "api_base": "wss://spark-api.xf-yun.com",
        "api_key_env": "SPARK_API_KEY",
        "docs": "https://www.xfyun.cn/doc/spark/",
        "icon": "🔴",
        "color": "#E62129",
        "special": "xfyun",
        "auth_type": "xfyun"
    },
    "xiaomi": {
        "name": "小米",
        "models": ["mimo-v2-flash", "mimo-v2-pro", "mimo-v2-omni"],
        "api_base": "https://api.xiaomimimo.com/v1",
        "api_key_env": "XIAOMI_API_KEY",
        "docs": "https://platform.xiaomimimo.com",
        "icon": "🟠",
        "color": "#FF6900"
    },
    
    # ==================== 第二梯队：AI六小龙 ====================
    "zhipu": {
        "name": "智谱AI",
        "models": ["glm-5", "glm-4-plus", "glm-4-flash", "glm-4-long", "glm-4.5", "glm-z1-flash"],
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
        "docs": "https://open.bigmodel.cn/dev/api",
        "icon": "💜",
        "color": "#7B1FA2"
    },
    "moonshot": {
        "name": "月之暗面",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "kimi-k2", "kimi-k2.5"],
        "api_base": "https://api.moonshot.cn/v1",
        "api_key_env": "MOONSHOT_API_KEY",
        "docs": "https://platform.moonshot.cn/docs",
        "icon": "🌙",
        "color": "#5C6BC0"
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-v3", "deepseek-r1"],
        "api_base": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "docs": "https://platform.deepseek.com/docs",
        "icon": "🐳",
        "color": "#0EA5E9"
    },
    "baichuan": {
        "name": "百川智能",
        "models": ["Baichuan4", "Baichuan3-Turbo", "Baichuan2-Turbo", "baichuan4-air"],
        "api_base": "https://api.baichuan-ai.com/v1",
        "api_key_env": "BAICHUAN_API_KEY",
        "docs": "https://platform.baichuan-ai.com/docs",
        "icon": "🏔️",
        "color": "#10B981"
    },
    "minimax": {
        "name": "MiniMax",
        "models": ["abab6.5-chat", "abab5.5-chat", "abab6.5s-chat", "abab7.0", "mini-max-m2.7"],
        "api_base": "https://api.minimax.chat/v1",
        "api_key_env": "MINIMAX_API_KEY",
        "docs": "https://platform.minimax.chat/document",
        "icon": "🎯",
        "color": "#F59E0B"
    },
    "lingyiwanwu": {
        "name": "零一万物",
        "models": ["yi-large", "yi-medium", "yi-spark", "yi-large-turbo", "yi-coder"],
        "api_base": "https://api.lingyiwanwu.com/v1",
        "api_key_env": "YI_API_KEY",
        "docs": "https://platform.lingyiwanwu.com/docs",
        "icon": "1️⃣",
        "color": "#6366F1"
    },
    "stepfun": {
        "name": "阶跃星辰",
        "models": ["step-1-8k", "step-2-16k", "step-1v-8k", "step-3-flash", "step-3.5-flash"],
        "api_base": "https://api.stepfun.com/v1",
        "api_key_env": "STEPFUN_API_KEY",
        "docs": "https://platform.stepfun.com/docs",
        "icon": "⭐",
        "color": "#EC4899"
    },
    
    # ==================== 第三梯队：其他厂商 ====================
    "meituan": {
        "name": "美团",
        "models": ["longcat-next", "longcat-flash", "longcat-next-native"],
        "api_base": "https://api.longcat.meituan.com/v1",
        "api_key_env": "MEITUAN_API_KEY",
        "docs": "https://longcat.meituan.com",
        "icon": "🐱",
        "color": "#FFD100"
    },
    "kunlun": {
        "name": "昆仑万维",
        "models": ["skywork-13b", "skywork-pro", "skywork-matrix", "skyreels-v4", "mureka-v9"],
        "api_base": "https://api.skywork.ai/v1",
        "api_key_env": "SKYWORK_API_KEY",
        "docs": "https://skywork.ai",
        "icon": "🏔️",
        "color": "#00A0E9"
    },
    "sensetime": {
        "name": "商汤科技",
        "models": ["SenseChat-5", "SenseChat-128K", "SenseNova-V6"],
        "api_base": "https://api.sensenova.cn/v1",
        "api_key_env": "SENSENOVA_API_KEY",
        "docs": "https://platform.sensenova.cn/docs",
        "icon": "🔬",
        "color": "#14B8A6"
    },
    "internlm": {
        "name": "书生·浦语",
        "models": ["internlm2.5-7b", "internlm2.5-20b", "internlm3-8b"],
        "api_base": "https://internlm.intern-ai.org.cn/api/v1",
        "api_key_env": "INTERNLM_API_KEY",
        "docs": "https://internlm.intern-ai.org.cn",
        "icon": "📚",
        "color": "#8B5CF6"
    },
    "huawei": {
        "name": "华为云",
        "models": ["pangu-nlp-large", "pangu-nlp-7b", "pangu-pro-moe", "pangu-5.0"],
        "api_base": "https://api.huaweicloud.com/nlp/v1",
        "api_key_env": "HUAWEI_API_KEY",
        "docs": "https://support.huaweicloud.com/modelarts/",
        "icon": "🏢",
        "color": "#FF0000",
        "special": "huawei",
        "auth_type": "huawei"
    },
    "360": {
        "name": "360智脑",
        "models": ["360gpt-pro", "360gpt-turbo", "nanami"],
        "api_base": "https://api.360.cn/v1",
        "api_key_env": "360_API_KEY",
        "docs": "https://ai.360.cn/",
        "icon": "🔎",
        "color": "#00A0E9"
    },
    "kuaishou": {
        "name": "快手可灵",
        "models": ["kling-1.0", "kling-1.5", "kling-pro"],
        "api_base": "https://app.klingai.com/cn/v1",
        "api_key_env": "KUAISHOU_API_KEY",
        "docs": "https://kling.kuaishou.com/",
        "icon": "📹",
        "color": "#FF4906"
    },
    "wangyi": {
        "name": "网易有道",
        "models": ["qanything", "qanything-plus"],
        "api_base": "https://api.youdao.com/v1",
        "api_key_env": "WANGYI_API_KEY",
        "docs": "https://ai.youdao.com/",
        "icon": "📖",
        "color": "#D6001C"
    },
    "modelbest": {
        "name": "面壁智能",
        "models": ["minicpm-3.0", "minicpm-2.4", "minicpm-s", "minicpm-moe"],
        "api_base": "https://api.modelbest.cn/v1",
        "api_key_env": "MODELBEST_API_KEY",
        "docs": "https://www.modelbest.cn/",
        "icon": "💡",
        "color": "#6366F1"
    },

    # ==================== 全球 Tier 1 ====================
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o3", "o3-mini", "o4-mini"],
        "api_base": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com/docs",
        "icon": "🧠",
        "color": "#10A37F"
    },
    "anthropic": {
        "name": "Anthropic",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-20250514", "claude-3.5-sonnet"],
        "api_base": "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "docs": "https://docs.anthropic.com",
        "icon": "🎭",
        "color": "#D97706",
        "special": "anthropic",
        "auth_type": "anthropic"
    },
    "google": {
        "name": "Google DeepMind",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemma-3-27b"],
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_API_KEY",
        "docs": "https://ai.google.dev",
        "icon": "🌐",
        "color": "#4285F4",
        "special": "google",
        "auth_type": "google"
    },
    "meta": {
        "name": "Meta Llama",
        "models": ["llama-4-maverick", "llama-4-scout", "llama-3.3-70b", "llama-3.1-405b"],
        "api_base": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "docs": "https://www.llama.com",
        "icon": "🦙",
        "color": "#1877F2"
    },
    "mistral": {
        "name": "Mistral AI",
        "models": ["mistral-large-latest", "mistral-small-latest", "pixtral-large-latest", "codestral-latest"],
        "api_base": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "docs": "https://docs.mistral.ai",
        "icon": "🌪️",
        "color": "#F97316"
    },
    "xai": {
        "name": "xAI Grok",
        "models": ["grok-3", "grok-3-mini", "grok-2"],
        "api_base": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "docs": "https://docs.x.ai",
        "icon": "🚀",
        "color": "#FFFFFF"
    },
    "cohere": {
        "name": "Cohere",
        "models": ["command-r-plus-08-2024", "command-r-08-2024", "command-a-03-2025"],
        "api_base": "https://api.cohere.ai/v2",
        "api_key_env": "COHERE_API_KEY",
        "docs": "https://docs.cohere.com",
        "icon": "🔗",
        "color": "#39594D",
        "special": "cohere",
        "auth_type": "cohere"
    },
    "ai21": {
        "name": "AI21 Labs",
        "models": ["jamba-1.6", "jamba-1.5-mini", "jamba-1.5-large"],
        "api_base": "https://api.ai21.com/studio/v1",
        "api_key_env": "AI21_API_KEY",
        "docs": "https://docs.ai21.com",
        "icon": "📊",
        "color": "#2563EB"
    },

    # ==================== 全球 Tier 2 ====================
    "perplexity": {
        "name": "Perplexity",
        "models": ["sonar-pro", "sonar-reasoning", "sonar-deep-research"],
        "api_base": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "docs": "https://docs.perplexity.ai",
        "icon": "🔍",
        "color": "#1DB954"
    },
    "groq": {
        "name": "Groq",
        "models": ["llama-4-scout-17b-16e-instruct", "mixtral-8x7b-32768", "gemma2-9b-it", "deepseek-r1-distill-llama-70b"],
        "api_base": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "docs": "https://console.groq.com/docs",
        "icon": "⚡",
        "color": "#F55036"
    },
    "reka": {
        "name": "Reka AI",
        "models": ["reka-core-20250115", "reka-flash-3", "reka-edge-3"],
        "api_base": "https://api.reka.ai",
        "api_key_env": "REKA_API_KEY",
        "docs": "https://docs.reka.ai",
        "icon": "🦓",
        "color": "#7C3AED"
    },
    "writer": {
        "name": "Writer",
        "models": ["palmyra-x4", "palmyra-creative"],
        "api_base": "https://api.writer.com/v1",
        "api_key_env": "WRITER_API_KEY",
        "docs": "https://dev.writer.com",
        "icon": "✍️",
        "color": "#EC4899"
    },
    "upstage": {
        "name": "Upstage (KR)",
        "models": ["solar-pro", "solar-mini"],
        "api_base": "https://api.upstage.ai/v1",
        "api_key_env": "UPSTAGE_API_KEY",
        "docs": "https://developers.upstage.ai",
        "icon": "☀️",
        "color": "#F97316"
    },
    "sambanova": {
        "name": "SambaNova",
        "models": ["Meta-Llama-3.3-70B-Instruct", "DeepSeek-R1", "Qwen2.5-72B-Instruct"],
        "api_base": "https://api.sambanova.ai/v1",
        "api_key_env": "SAMBANOVA_API_KEY",
        "docs": "https://community.sambanova.ai",
        "icon": "💨",
        "color": "#E87000"
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "models": ["nvidia/llama-3.1-nemotron-ultra-253b-v1", "nvidia/nemotron-4-340b-instruct"],
        "api_base": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "docs": "https://build.nvidia.com",
        "icon": "🖥️",
        "color": "#76B900"
    }
}

# 生成所有模型列表
ALL_MODELS = []
for provider_id, provider in LLM_PROVIDERS.items():
    for model in provider["models"]:
        ALL_MODELS.append({
            "id": f"{provider_id}:{model}",
            "provider": provider_id,
            "provider_name": provider["name"],
            "model": model,
            "icon": provider["icon"],
            "color": provider["color"]
        })

# Battle Mode 专用模型池（全部国产）
BATTLE_MODELS = [
    # 已验证可用的文本对话模型
    m for m in ALL_MODELS if m["provider"] in [
        "zhipu",      # 智谱AI - GLM系列
        "stepfun",    # 阶跃星辰 - Step系列
        "alibaba",    # 阿里巴巴 - 通义千问
        "tencent",    # 腾讯 - 混元
        "byteDance",  # 字节跳动 - 豆包

        "openai",     # OpenAI - GPT系列
        "anthropic",  # Anthropic - Claude系列
        "google",     # Google - Gemini系列
        "mistral",    # Mistral AI
        "xai",        # xAI - Grok系列
        "cohere",     # Cohere Command-R
        "groq",       # Groq - 高速推理
        "perplexity", # Perplexity - 联网搜索
        "moonshot",   # 月之暗面 - Kimi
    ]
]

# 模型路由映射表：极速版 / 专家版
# 每个 provider 对应一个快速模型（极速）和一个强力模型（专家）
# 管理员可在后台修改，修改后存入数据库覆盖此默认值
MODEL_ROUTING = {
    "alibaba":   {"name": "通义千问",  "fast": "qwen-turbo",     "expert": "qwen-max"},
    "baidu":     {"name": "文心一言",  "fast": "ernie-speed-8k", "expert": "ernie-4.0-8k"},
    "tencent":   {"name": "腾讯混元",  "fast": "hunyuan-lite",    "expert": "hunyuan-pro"},
    "byteDance": {"name": "豆包",      "fast": "doubao-seed-2-0-pro-260215", "expert": "doubao-seed-2-0-pro-260215"},
    "zhipu":     {"name": "智谱GLM",   "fast": "glm-4-flash",    "expert": "glm-5"},
    "moonshot":  {"name": "Kimi",      "fast": "moonshot-v1-8k",  "expert": "kimi-k2"},
    "deepseek":  {"name": "DeepSeek",  "fast": "deepseek-chat",   "expert": "deepseek-reasoner"},
    "baichuan":  {"name": "百川",      "fast": "Baichuan2-Turbo", "expert": "Baichuan4"},
    "minimax":   {"name": "MiniMax",   "fast": "abab6.5s-chat",  "expert": "abab7.0"},
    "stepfun":   {"name": "阶跃星辰",  "fast": "step-1-8k",      "expert": "step-2-16k"},
    "lingyiwanwu":{"name": "零一万物",  "fast": "yi-spark",       "expert": "yi-large"},
    "xiaomi":    {"name": "小米MiMo",  "fast": "mimo-v2-flash",  "expert": "mimo-v2-pro"},
    "xfyun":     {"name": "科大讯飞",  "fast": "spark-lite",     "expert": "spark-max"},
    "meituan":   {"name": "美团LongCat", "fast": "longcat-flash", "expert": "longcat-next"},
    "sensetime": {"name": "商汤",      "fast": "SenseChat-5",    "expert": "SenseNova-V6"},
    "internlm":  {"name": "书生浦语",  "fast": "internlm2.5-7b", "expert": "internlm2.5-20b"},
    "kunlun":    {"name": "昆仑天工",  "fast": "skywork-13b",    "expert": "skywork-pro"},
    "360":       {"name": "360智脑",   "fast": "360gpt-turbo",  "expert": "360gpt-pro"},
    "huawei":    {"name": "华为盘古",  "fast": "pangu-nlp-7b",  "expert": "pangu-nlp-large"},
    "kuaishou":  {"name": "快手可灵",  "fast": "kling-1.0",      "expert": "kling-pro"},
    "wangyi":    {"name": "网易有道",  "fast": "qanything",     "expert": "qanything-plus"},
    "openai":    {"name": "OpenAI",       "fast": "gpt-4o-mini",        "expert": "gpt-4o"},
    "anthropic": {"name": "Anthropic",    "fast": "claude-3.5-haiku",     "expert": "claude-sonnet-4-20250514"},
    "google":    {"name": "Google Gemini","fast": "gemini-2.0-flash",     "expert": "gemini-2.5-pro"},
    "meta":      {"name": "Meta Llama",   "fast": "llama-4-scout",        "expert": "llama-4-maverick"},
    "mistral":   {"name": "Mistral",      "fast": "mistral-small-latest", "expert": "mistral-large-latest"},
    "xai":       {"name": "xAI Grok",    "fast": "grok-3-mini",          "expert": "grok-3"},
    "cohere":    {"name": "Cohere",       "fast": "command-r-08-2024",    "expert": "command-r-plus-08-2024"},
    "ai21":      {"name": "AI21 Jamba",   "fast": "jamba-1.5-mini",       "expert": "jamba-1.6"},
    "perplexity":{"name": "Perplexity",   "fast": "sonar-pro",            "expert": "sonar-deep-research"},
    "groq":      {"name": "Groq",         "fast": "gemma2-9b-it",         "expert": "llama-4-scout-17b-16e-instruct"},
    "reka":      {"name": "Reka",         "fast": "reka-flash-3",          "expert": "reka-core-20250115"},
    "writer":    {"name": "Writer",       "fast": "palmyra-creative",      "expert": "palmyra-x4"},
    "upstage":   {"name": "Upstage",      "fast": "solar-mini",             "expert": "solar-pro"},
    "sambanova": {"name": "SambaNova",    "fast": "Llama-4-Maverick-17B",  "expert": "Meta-Llama-3.3-70B-Instruct"},
    "nvidia":    {"name": "NVIDIA",       "fast": "nvidia/nemotron-4-340b-instruct", "expert": "nvidia/llama-3.1-nemotron-ultra-253b-v1"},
    "modelbest": {"name": "面壁智能",  "fast": "minicpm-2.4",   "expert": "minicpm-3.0"},

    # ==================== 全球 Tier 1：国际旗舰大模型 ====================
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "o3", "o3-mini", "o4-mini"],
        "api_base": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com/docs",
        "icon": "🧠",
        "color": "#10A37F"
    },
    "anthropic": {
        "name": "Anthropic",
        "models": ["claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-20250514", "claude-3.5-sonnet", "claude-3.5-haiku"],
        "api_base": "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "docs": "https://docs.anthropic.com",
        "icon": "🎭",
        "color": "#D97706",
        "special": "anthropic",
        "auth_type": "anthropic"
    },
    "google": {
        "name": "Google DeepMind",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemma-3-27b"],
        "api_base": "https://generativelanguage.googleapis.com/v1beta",
        "api_key_env": "GOOGLE_API_KEY",
        "docs": "https://ai.google.dev",
        "icon": "🌐",
        "color": "#4285F4",
        "special": "google",
        "auth_type": "google"
    },
    "meta": {
        "name": "Meta Llama",
        "models": ["llama-4-maverick", "llama-4-scout", "llama-3.3-70b", "llama-3.1-405b"],
        "api_base": "https://api.together.xyz/v1",
        "api_key_env": "TOGETHER_API_KEY",
        "docs": "https://www.llama.com",
        "icon": "🦙",
        "color": "#1877F2"
    },
    "mistral": {
        "name": "Mistral AI",
        "models": ["mistral-large-latest", "mistral-small-latest", "pixtral-large-latest", "codestral-latest"],
        "api_base": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "docs": "https://docs.mistral.ai",
        "icon": "🌪️",
        "color": "#F97316"
    },
    "xai": {
        "name": "xAI Grok",
        "models": ["grok-3", "grok-3-mini", "grok-2"],
        "api_base": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "docs": "https://docs.x.ai",
        "icon": "🚀",
        "color": "#FFFFFF"
    },
    "cohere": {
        "name": "Cohere",
        "models": ["command-r-plus-08-2024", "command-r-08-2024", "command-a-03-2025"],
        "api_base": "https://api.cohere.ai/v2",
        "api_key_env": "COHERE_API_KEY",
        "docs": "https://docs.cohere.com",
        "icon": "🔗",
        "color": "#39594D",
        "special": "cohere",
        "auth_type": "cohere"
    },
    "ai21": {
        "name": "AI21 Labs",
        "models": ["jamba-1.6", "jamba-1.5-mini", "jamba-1.5-large"],
        "api_base": "https://api.ai21.com/studio/v1",
        "api_key_env": "AI21_API_KEY",
        "docs": "https://docs.ai21.com",
        "icon": "📊",
        "color": "#2563EB"
    },

    # ==================== 全球 Tier 2：区域与开放生态 ====================
    "perplexity": {
        "name": "Perplexity",
        "models": ["sonar-pro", "sonar-reasoning", "sonar-deep-research"],
        "api_base": "https://api.perplexity.ai",
        "api_key_env": "PERPLEXITY_API_KEY",
        "docs": "https://docs.perplexity.ai",
        "icon": "🔍",
        "color": "#1DB954"
    },
    "groq": {
        "name": "Groq",
        "models": ["llama-4-scout-17b-16e-instruct", "mixtral-8x7b-32768", "gemma2-9b-it", "deepseek-r1-distill-llama-70b"],
        "api_base": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "docs": "https://console.groq.com/docs",
        "icon": "⚡",
        "color": "#F55036"
    },
    "reka": {
        "name": "Reka AI",
        "models": ["reka-core-20250115", "reka-flash-3", "reka-edge-3"],
        "api_base": "https://api.reka.ai",
        "api_key_env": "REKA_API_KEY",
        "docs": "https://docs.reka.ai",
        "icon": "🦓",
        "color": "#7C3AED"
    },
    "writer": {
        "name": "Writer",
        "models": ["palmyra-x4", "palmyra-creative", "palmyra-medical"],
        "api_base": "https://api.writer.com/v1",
        "api_key_env": "WRITER_API_KEY",
        "docs": "https://dev.writer.com",
        "icon": "✍️",
        "color": "#EC4899"
    },
    "upstage": {
        "name": "Upstage (KR)",
        "models": ["solar-pro", "solar-mini"],
        "api_base": "https://api.upstage.ai/v1",
        "api_key_env": "UPSTAGE_API_KEY",
        "docs": "https://developers.upstage.ai",
        "icon": "☀️",
        "color": "#F97316"
    },
    "sambanova": {
        "name": "SambaNova",
        "models": ["Meta-Llama-3.3-70B-Instruct", "DeepSeek-R1", "Qwen2.5-72B-Instruct", "Llama-4-Maverick-17B"],
        "api_base": "https://api.sambanova.ai/v1",
        "api_key_env": "SAMBANOVA_API_KEY",
        "docs": "https://community.sambanova.ai",
        "icon": "💨",
        "color": "#E87000"
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "models": ["nvidia/llama-3.1-nemotron-ultra-253b-v1", "nvidia/nemotron-4-340b-instruct"],
        "api_base": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "docs": "https://build.nvidia.com",
        "icon": "🖥️",
        "color": "#76B900"
    },

}

# 默认启用的模型
DEFAULT_ENABLED_PROVIDERS = ["deepseek", "zhipu", "alibaba", "moonshot", "baidu", "tencent"]
