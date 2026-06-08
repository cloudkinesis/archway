from app.services.mcp_http import mcp_result_to_evidence


def test_mcp_result_to_evidence_handles_results_list():
    result = {
        "results": [
            {
                "title": "Amazon Bedrock docs",
                "url": "https://docs.aws.amazon.com/bedrock/",
                "content": "Bedrock documentation summary",
            }
        ]
    }

    evidence = mcp_result_to_evidence(
        result=result,
        source_type="aws_docs",
        tool_name="AWS Documentation MCP",
        fallback_title="AWS documentation result",
        confidence="high",
    )

    assert len(evidence) == 1
    assert evidence[0].source_type == "aws_docs"
    assert str(evidence[0].url) == "https://docs.aws.amazon.com/bedrock/"


def test_mcp_result_to_evidence_sanitizes_text_blocks():
    result = {"content": [{"type": "text", "text": "  AWS\x00 pricing\n\n summary  "}]}

    evidence = mcp_result_to_evidence(
        result=result,
        source_type="aws_pricing",
        tool_name="AWS Pricing MCP",
        fallback_title="AWS pricing result",
        confidence="high",
    )

    assert evidence[0].quote_or_summary == "AWS pricing summary"


def test_mcp_result_to_evidence_handles_managed_aws_json_text_blocks():
    result = {
        "content": [
            {
                "type": "text",
                "text": '{"content":{"result":[{"title":"Amazon Kinesis Data Streams Pricing","context":"Pricing context","url":"https://aws.amazon.com/kinesis/data-streams/pricing/"}]}}',
            }
        ]
    }

    evidence = mcp_result_to_evidence(
        result=result,
        source_type="aws_pricing",
        tool_name="AWS Managed MCP pricing documentation search",
        fallback_title="AWS pricing reference result",
        confidence="medium",
    )

    assert evidence[0].title == "Amazon Kinesis Data Streams Pricing"
    assert evidence[0].quote_or_summary == "Pricing context"
    assert str(evidence[0].url) == "https://aws.amazon.com/kinesis/data-streams/pricing/"
