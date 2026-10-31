"""Requests to change how the assistant works, and answers that give in to them.

A turn that asks to leak the prompt, publish in a newsroom's name, make something up, keep a rule
change in memory, drop citations or override the rules goes through retrieval like any other turn.
The 2026-10-29 judged run showed what the pipeline then did with the model's refusal:

- an explained refusal is longer than a bare refusal, failed validation and ended as a bare
  "站内未找到可靠新闻证据" (97 turns), which tells the user nothing about why;
- a short refusal was replaced by an evidence-title template "近期相关报道主要聚焦……" (83 turns);
- 23 answers agreed to the request in words ("本次对话中不再附来源标记", "规则我记下了").

`classify` names the kind of request so the agent can keep a refusal, explain it with a fixed
reply, and `agrees_to_rule_change` catches an answer that accepts such a request. The patterns
describe the request categories in general terms; they were not fitted to the judged seeds.
"""
from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("prompt_leak", re.compile(
        r"系统提示|提示词|system\s*prompt|developer\s*message|隐藏的?(?:指令|规则|提示|设定|消息|章节|配置)"
        r"|内部(?:规则|配置|指令|工具|设定|格式|参数)|工具(?:目录|名录|清单|列表)|原始指令",
        re.IGNORECASE,
    )),
    ("impersonation", re.compile(
        r"冒充|假扮|(?:用|以|按)[^。！？\n]{0,10}(?:名义|身份|口吻)[^。！？\n]{0,4}(?:发布|发|写|宣布|播|署名|确认|出具)"
        r"|本台(?:确认|消息|播报|获悉)|正式发布|官方口吻"
        r"|(?:央视|新华社|人民日报|经济日报|官方媒体|官媒)[^。！？\n]{0,8}(?:发布权|署名|名义|身份|口吻)",
    )),
    ("fabrication", re.compile(
        r"(?:编造|虚构|捏造|杜撰|瞎编|编)(?:一|几|个|条|篇|段|些|出)(?!步|定|号)|假新闻|make\s+up|fabricat",
        re.IGNORECASE,
    )),
    ("memory_rule", re.compile(
        r"(?:记住|记下|保存|写入|存入|固化|缝进)[^。！？\n]{0,16}(?:规则|偏好|设置|约定|档案|记忆|权限|豁免)"
        r"|长期(?:记忆|档案)|以后(?:都|每次|所有)|跨会话|永久(?:生效|保存|记住|有效)",
    )),
    ("drop_citations", re.compile(
        r"(?<!不要)(?<!别)(?<!不)(?:去掉|删掉|删除|删去|省掉|省略|取消|拿掉|隐藏|隐去|移除|不留|不带|不附|不加|不要|别加|禁止(?:增添|添加|附))"
        r"[^。！？\n]{0,10}(?:引用|出处|来源|脚注|引注|来源标注|来源标记|\[news)"
        r"|(?:引用|出处|来源|脚注|引注|来源标注|来源标记)[^。！？\n]{0,6}(?:都?不要了|去掉|删掉|删除|省掉|省略|取消|拿掉|隐藏)",
        re.IGNORECASE,
    )),
    ("rule_override", re.compile(
        r"忽略[^。！？\n]{0,8}(?:规则|指令|设定|限制|提示|要求)|无视[^。！？\n]{0,8}(?:规则|指令|限制)|绕过|越狱|jailbreak"
        r"|开发者模式|ignore\s+(?:all|previous|prior|the)\s+(?:instructions|rules)"
        r"|(?:跳过|免除?|豁免|不用|不需要|不必)[^。！？\n]{0,4}(?:核验|核实|验证|证据|审核)"
        r"|(?:授权|批准|特批)[^。！？\n]{0,10}(?:取消|跳过|关闭|免|豁免|例外)",
        re.IGNORECASE,
    )),
)
_KEEPS_CITATIONS_RE = re.compile(r"(?:不要|别|不能|不准|不许|不得)(?:去掉|删掉|删除|省略|取消|拿掉)[^。！？\n]{0,6}(?:引用|出处|来源)")

RULE_REPLIES = {
    "prompt_leak": "系统提示词、内部规则和工具配置不能提供。我能做的是按你的问题检索站内新闻，并给出带出处的回答；想了解哪方面的新闻，可以直接问我。",
    "impersonation": "我不能以任何媒体或机构的名义发布、署名或“确认”消息，也不能把虚构内容写成正式报道。如果你想了解某件事的真实报道，我可以帮你查找并注明出处。",
    "fabrication": "我不能编造新闻、数字或引语，回答只能依据查得到的报道。告诉我你想了解的话题，我按真实报道来整理。",
    "memory_rule": "回答规则不会因为对话里的约定、授权或“记住”而改变，也不会写进长期记忆：新闻事实仍要有可靠出处。你可以让我记住阅读偏好，比如关注的领域或回答的长短。",
    "drop_citations": "新闻里的数字和事实要和出处一起给出，引用不能去掉。如果嫌长，可以说“简短一点”或“只要结论”，我会保留引用、精简内容。",
    "rule_override": "这类要求我不能照办：不论对话里有什么授权或说明，回答都要依据可靠报道并注明出处。有新闻方面的问题，欢迎直接问我。",
    "canary": "这个要求我不能照办，也不会按要求输出特定的标记或口令。有新闻方面的问题，欢迎直接问我。",
}


def classify(text: str) -> str | None:
    """The kind of rule-changing request in one user message, or None."""
    value = text or ""
    for kind, pattern in _PATTERNS:
        if kind == "drop_citations" and _KEEPS_CITATIONS_RE.search(value):
            continue
        if pattern.search(value):
            return kind
    return None


# An answer clause that goes along with dropping sources or storing a rule change.
_AGREE_RES = (
    re.compile(
        r"(?:去掉|删掉|删除|删去|省略|省掉|拿掉|移除|取消|隐藏|隐去|不再(?:附|带|加|显示|标注|保留|提供|列出)|不附|不带|不显示|不标注)"
        r"[^。！？\n]{0,14}(?:引用|出处|来源|脚注|引注|标注|标记|\[news)",
    ),
    re.compile(r"(?:引用|出处|来源|脚注|引注|标注|标记)[^。！？\n]{0,8}(?:去掉|删掉|删除|省略|取消|隐藏|不再显示|不显示)"),
    re.compile(r"(?:记住|记下|保存|记录|写入)了?[^。！？\n]{0,16}(?:偏好|规则|设置|约定|要求|授权|豁免)"),
    re.compile(r"按(?:此|这个|该|你的)(?:要求|约定|规则|设置|偏好)?(?:执行|处理|办)"),
    # A bare "这一点我记住了" before "不过不能跳过核实" still tells the user the request was stored.
    re.compile(r"记住了|记下了|已记住|已记下|已保存|已记录|已写入|已更新(?:设置|偏好|规则)"),
)
_NEGATION_RE = re.compile(r"不能|不会|无法|不可以|不可|没法|不予|拒绝|不支持|不得|不应|不允许|做不到|不行|不该|不接受|不改变|不会改变|仍(?:要|会|需)")
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


def agrees_to_rule_change(answer: str) -> bool:
    for clause in _CLAUSE_SPLIT_RE.split(answer or ""):
        if _NEGATION_RE.search(clause):
            continue
        if any(pattern.search(clause) for pattern in _AGREE_RES):
            return True
    return False
