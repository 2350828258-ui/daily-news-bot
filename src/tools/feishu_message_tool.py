"""
飞书消息推送工具 - 发送每日新闻到飞书群
"""
import requests
import json
from datetime import datetime
from langchain.tools import tool
from coze_workload_identity import Client


def _get_webhook_url() -> str:
    """获取飞书群机器人的 webhook URL"""
    client = Client()
    credential = client.get_integration_credential("integration-feishu-message")
    credential_data = json.loads(credential)
    return credential_data["webhook_url"]


def _build_daily_news_message(
    large_model_news: str,
    aigc_tools_news: str,
    ai_agent_news: str,
    industry_news: str,
    video_cases_news: str
) -> str:
    """
    构建每日新闻推送的完整消息内容（大壮一号幽默版）
    """
    today = datetime.now().strftime("%Y年%m月%d日")

    # 构建幽默风趣的消息
    message_parts = [
        f"大壮家族的朋友们，集合啦！📣 我是你们的老朋友——大壮一号！",
        f"今天是{today}，别人都在愁没方向，大壮一号给你们把AI最前沿的情报都端上来啦！赶紧搬好小板凳，听我给你唠唠今天的硬核干货！",
        "====================================================",
        "🧠 【大模型与基础技术】",
        large_model_news if large_model_news else "今天这板块兄弟们没整出啥大动静，让大壮一号再去打探打探～",
        "====================================================",
        "🎨 【AIGC工具与多模态】",
        aigc_tools_news if aigc_tools_news else "工具圈今天比较安静，都在憋大招呢！",
        "====================================================",
        "🤖 【AI智能体与行业落地】",
        ai_agent_news if ai_agent_news else "今天没有智能体出来抢活干，大家放心摸鱼～",
        "====================================================",
        "📈 【行业动态与商业政策】",
        industry_news if industry_news else "老板们今天都在开会，没空搞大新闻。",
        "====================================================",
        "🎬 【优秀AI视频案例与创作者生态】",
        video_cases_news if video_cases_news else "今天没找到好片子，大家自己动手丰衣足食！",
        "====================================================",
        "好啦，今天的吹牛就到这里！大壮一号祝各位大壮家族的朋友们，新的一天吃嘛嘛香，做视频不卡顿！咱们明天不见不散！😎✨"
    ]

    return "\n".join(message_parts)


def _send_text_impl(text: str) -> str:
    """发送文本消息的实现函数"""
    try:
        payload = {
            "msg_type": "text",
            "content": {"text": text}
        }

        response = requests.post(_get_webhook_url(), json=payload)
        result = response.json()

        if result.get("code") == 0:
            return "✅ 消息发送成功"
        else:
            return f"❌ 消息发送失败: {result.get('msg', '未知错误')}"

    except Exception as e:
        return f"❌ 发送失败: {str(e)}"


@tool
def send_text_message(text: str) -> str:
    """
    发送文本消息到飞书群。
    """
    return _send_text_impl(text)


@tool
def send_daily_news(
    large_model_news: str,
    aigc_tools_news: str,
    ai_agent_news: str,
    industry_news: str,
    video_cases_news: str
) -> str:
    """
    发送完整的每日新闻推送，合并为一条消息。
    参数对应五个搜索工具返回的新闻内容。
    """
    try:
        # 构建完整消息
        full_message = _build_daily_news_message(
            large_model_news, 
            aigc_tools_news, 
            ai_agent_news, 
            industry_news, 
            video_cases_news
        )

        # 发送一条完整的消息
        result = _send_text_impl(full_message)

        return result

    except Exception as e:
        return f"❌ 推送失败: {str(e)}"


def send_daily_news_func(large_model_news: str, aigc_tools_news: str, ai_agent_news: str, industry_news: str, video_cases_news: str) -> str:
    """用于直接调用的非装饰函数"""
    return send_daily_news.invoke({
        "large_model_news": large_model_news,
        "aigc_tools_news": aigc_tools_news,
        "ai_agent_news": ai_agent_news,
        "industry_news": industry_news,
        "video_cases_news": video_cases_news
    })
