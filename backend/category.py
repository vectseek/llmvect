# -*- coding: utf-8 -*-
"""
问题分类引擎 - 根据问题内容自动分类到 综合/编程/创意写作 板块
"""

import re

# 编程关键词（中英文）
CODING_KEYWORDS = [
    # 英文
    r'\bcode\b', r'\bcoding\b', r'\bprogram\b', r'\bprogramming\b', r'\balgorithm\b',
    r'\bdebug\b', r'\bdebugging\b', r'\bfunction\b', r'\bclass\b', r'\bmethod\b',
    r'\bvariable\b', r'\bloop\b', r'\barray\b', r'\bdict\b', r'\blist\b',
    r'\bregex\b', r'\bapi\b', r'\bhtml\b', r'\bcss\b', r'\bjavascript\b',
    r'\btypescript\b', r'\bpython\b', r'\bjava\b', r'\bgo\b', r'\brust\b',
    r'(?:^|\s)c\+\+(?:\s|$)', r'\bsql\b', r'\bdatabase\b', r'\bserver\b', r'\bclient\b',
    r'\bgit\b', r'\bdocker\b', r'\bkubernetes\b', r'\blinux\b', r'\bshell\b',
    r'\bbash\b', r'\bscript\b', r'\bcompiler\b', r'\bruntime\b', r'\bframework\b',
    r'\brefactor\b', r'\boptimize\b', r'\bperformance\b', r'\bleetcode\b',
    r'\bimplement\b', r'\bsort\b', r'\bsearch\b', r'\btree\b', r'\bgraph\b',
    r'\bstack\b', r'\bqueue\b', r'\bhash\b', r'\brecursive\b', r'\biteration\b',
    r'\basync\b', r'\bawait\b', r'\bthread\b', r'\bconcurrent\b', r'\bparallel\b',
    r'\berror\b', r'\bexception\b', r'\bbug\b', r'\bfix\b', r'\bpatch\b',
    r'\bdeploy\b', r'\bci.?cd\b', r'\btest\b', r'\bunit.?test\b',
    r'\breact\b', r'\bvue\b', r'\bangular\b', r'\bnode\b', r'\bexpress\b',
    r'\bdjango\b', r'\bflask\b', r'\bfastapi\b', r'\bspring\b',
    r'\bwebhook\b', r'\bendpoint\b', r'\bmiddleware\b',
    # 中文
    '编程', '代码', '算法', '调试', '函数', '变量', '循环', '数组',
    '排序', '搜索', '递归', '实现', '重构', '优化', '部署', '接口',
    '服务端', '客户端', '前端', '后端', '全栈', '数据库', '运维',
    '并发', '线程', '进程', '异步', '同步', '框架', '库', '模块',
    '组件', '渲染', '编译', '解析', '序列化', '反序列化',
    '报错', '报BUG', '修bug', '写一个', '帮我写.*程序', '帮我写.*脚本',
    '写一个.*函数', '实现一个', '如何实现', '代码实现', '代码示例',
    'python', 'java', 'javascript', 'typescript', 'go语言', 'rust',
    r'(?:^|\s)c\+\+(?:\s|$)', r'(?:^|\s)c#(?:\s|$)', 'sql', 'html', 'css', 'shell', 'bash',
    'leetcode', '力扣', '刷题', '笔试题', '面试题.*编程',
    '数据结构', '时间复杂度', '空间复杂度', '动态规划', '贪心',
    '回溯', '分治', '二分', '双指针', '滑动窗口',
]

# 创意写作关键词
WRITING_KEYWORDS = [
    # 英文
    r'\bstor(y|ies|ytelling)\b', r'\bnovel\b', r'\bfiction\b', r'\bpoem\b', r'\bpoetry\b',
    r'\bwrite\b', r'\bwriting\b', r'\bcreative\b', r'\bnarrative\b', r'\bplot\b',
    r'\bcharacter\b', r'\bdialogue\b', r'\bchapter\b', r'\bscene\b',
    r'\bsong\b', r'\blyrics?\b', r'\brap\b', r'\bcompose\b',
    r'\bslogan\b', r'\bcopywrit\w+\b', r'\bheadline\b', r'\btagline\b',
    r'\bbrainstorm\b', r'\bidea\b', r'\bimagine\b', r'\bfantasize\b',
    # 中文
    '写作', '小说', '故事', '诗歌', '诗', '词', '散文', '随笔',
    '文案', '广告', '宣传', '营销文案', '品牌文案', 'slogan', '标语',
    '创意', '创作', '构思', '想象', '幻想', '虚构', '编故事',
    '剧本', '台词', '对白', '场景描写', '人物塑造', '角色设定',
    '开头', '结尾', '续写', '改写', '润色', '修饰',
    '写一首', '写一篇', '写一段', '帮我写.*诗', '帮我写.*故事',
    '帮我写.*小说', '帮我写.*文案', '帮我写.*广告',
    '歌词', '作曲', '填词', 'rap',
    '日记', '游记', '读后感', '观后感',
    '起名', '取名', '命名',
    '演讲稿', '致辞', '祝福语', '贺词',
    '微小说', '短篇', '长篇', '连载',
]

# 编译正则
_CODING_PATTERNS = [re.compile(p, re.IGNORECASE) for p in CODING_KEYWORDS]
_WRITING_PATTERNS = [re.compile(p, re.IGNORECASE) for p in WRITING_KEYWORDS]


def classify_category(question: str) -> str:
    """
    根据问题内容自动分类到 综合/编程/创意写作
    
    Returns:
        "coding" | "writing" | "overall"
    """
    if not question or not question.strip():
        return "overall"
    
    q = question.strip()
    
    # 计算匹配分数
    coding_score = sum(1 for p in _CODING_PATTERNS if p.search(q))
    writing_score = sum(1 for p in _WRITING_PATTERNS if p.search(q))
    
    # 需要至少2个关键词匹配才确认分类（避免误判）
    if coding_score >= 2 and coding_score > writing_score:
        return "coding"
    elif writing_score >= 2 and writing_score > coding_score:
        return "writing"
    elif coding_score >= 1 and coding_score == writing_score:
        # 平局时看哪个分数更高（单个匹配更强烈的）
        return "overall"
    elif coding_score >= 1:
        return "coding"
    elif writing_score >= 1:
        return "writing"
    
    return "overall"


# 分类中文名映射
CATEGORY_NAMES = {
    "overall": "综合",
    "coding": "编程",
    "writing": "创意写作",
}

CATEGORY_ICONS = {
    "overall": "🏆",
    "coding": "💻",
    "writing": "✍️",
}
