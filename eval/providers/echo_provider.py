"""echo provider(数据映射评测;断言直调 resolve,provider 输出不参与判定)。"""


def call_api(prompt: str, context, options) -> dict:
    return {"output": prompt}
