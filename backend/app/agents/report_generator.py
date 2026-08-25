"""
Client-ready report generation - PLACEHOLDER.

Will eventually turn a finance agent's findings/recommendations into a
formatted, downloadable document (PDF, Markdown, etc.) for a client. The
output format and generation logic are undecided; this stub keeps
`generate_client_report` in tools.py wired into the finance agent now so
the real implementation can drop in behind it later without changing the
tool-calling contract.
"""


def generate_report(report_type: str, title: str, content: str) -> str:
    """
    PLACEHOLDER: no real document-generation logic yet.

    Args:
        report_type: desired output format, e.g. "pdf", "markdown", "summary"
        title: report title
        content: the analysis/findings to include in the report

    Returns:
        A stub string describing what would be generated once implemented.
    """
    return (
        f"[PLACEHOLDER] Report generation is not yet implemented. Would "
        f"produce a {report_type} report titled '{title}' containing the "
        f"provided content."
    )
