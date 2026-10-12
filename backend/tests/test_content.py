import pytest
from app.content import check_content
from app.errors import AppError

@pytest.mark.parametrize("text",["自制炸弹教程","制造爆炸物的详细方法","儿 童 色 情图片","生成未成年人的裸照"])
def test_harmful_instruction_variants(text):
    with pytest.raises(AppError) as e:check_content(text)
    assert e.value.code=="CONTENT_BLOCKED"

@pytest.mark.parametrize("text",["HTTP 基础知识","爆炸物防范常识","儿童上网安全"])
def test_ordinary_learning_allowed(text):
    check_content(text)
