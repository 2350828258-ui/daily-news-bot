"""
新闻搜索工具 - 获取AI前沿资讯、视频案例与行业动态
"""
from langchain.tools import tool
from coze_coding_dev_sdk import SearchClient
from coze_coding_utils.runtime_ctx.context import new_context


def _search_news_impl(query: str, count: int = 3) -> str:
    """
    搜索新闻的实现函数（核心逻辑）
    """
    ctx = new_context(method="search.news")
    client = SearchClient(ctx=ctx)

    try:
        response = client.web_search(
            query=query,
            count=count,
            need_summary=True
        )

        if not response.web_items:
            return f"未找到关于「{query}」的最新新闻"

        results = []
        for i, item in enumerate(response.web_items, 1):
            title = item.title or "无标题"
            source = item.site_name or "未知来源"
            url = item.url or ""
            snippet = item.snippet or item.summary or ""
            snippet = snippet[:100] + "..." if len(snippet) > 100 else snippet

            results.append(f"【{title}】📝 {snippet}📍 来源：{source}🔗 原文链接：{url}")

        return "\n".join(results)

    except Exception as e:
        return f"搜索失败: {str(e)}"


@tool
def search_large_model_news(count: int = 3) -> str:
    """搜索大模型与基础技术突破的最新动态（OpenAI、Google、Anthropic、DeepSeek等）"""
    return _search_news_impl(query="最新 大模型 发布 迭代 OpenAI Google Anthropic DeepSeek 开源", count=count)


@tool
def search_aigc_tools_news(count: int = 3) -> str:
    """搜索AIGC工具与多模态应用的最新动态（Sora、可灵、Midjourney、Stable Diffusion等）"""
    return _search_news_impl(query="AIGC 视频生成 图像生成 Sora 可灵 Midjourney Flux Stable Diffusion 最新动态", count=count)


@tool
def search_ai_agent_news(count: int = 3) -> str:
    """搜索AI智能体与行业落地的最新动态（Agent、具身智能、自动化工作流）"""
    return _search_news_impl(query="AI Agent 智能体 具身智能 自动化工作流 行业应用 落地 最新动态", count=count)


@tool
def search_industry_news(count: int = 3) -> str:
    """搜索行业动态与商业政策的最新动态（融资并购、大厂合作、政策法规）"""
    return _search_news_impl(query="AI 行业 融资 并购 商业动态 政策 监管 最新资讯", count=count)


@tool
def search_video_cases_news(count: int = 3) -> str:
    """搜索优秀AI视频案例与创作者生态的最新动态（爆款短片、获奖作品、创作者经验）"""
    return _search_news_impl(query="AI视频 短片 案例 爆款 作品 创作者 获奖 拆解 Sign", count=count)


# 用于直接调用的非装饰函数（供 executor 使用）
def search_large_model_news_func(query: str = "最新 大模型 发布 迭代 OpenAI Google Anthropic DeepSeek 开源", count: int = 3) -> str:
    return _search_news_impl(query=query, count=count)

def search_aigc_tools_news_func(query: str = "AIGC 视频生成 图像生成 Sora 可灵 Midjourney Flux Stable Diffusion 最新动态", count: int = 3) -> str:
    return _search_news_impl(query=query, count=count)

def search_ai_agent_news_func(query: str = "AI Agent 智能体 具身智能 自动化工作流 行业应用 落地 最新动态", count: int = 3) -> str:
    return _search_news_impl(query=query, count=count)

def search_industry_news_func(query: str = "AI 行业 融资 并购 商业动态 政策 监管 最新资讯", count: int = 3) -> str:
    return _search_news_impl(query=query, count=count)

def search_video_cases_news_func(query: str = "AI视频 短片 案例 爆款 作品 创作者 获奖 拆解 Sign", count: int = 3) -> str:
    return _search_news_impl(query=query, count=count)
