from agent import run_agent, Tool
from tools_read import read_file_tool_def, read_file_impl
from tools_list import list_files_tool_def, list_files_impl
from tools_edit import edit_file_tool_def, edit_file_impl
from tools_line_edit import line_edit_tool_def, line_edit_impl
from tools_grep import grep_tool_def, grep_impl
from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl
from tools_glob_file_search import glob_file_search_tool_def, glob_file_search_impl
from tools_codebase_search import codebase_search_tool_def, codebase_search_impl
from tools_apply_patch import apply_patch_tool_def, apply_patch_impl
from tools_delete_file import delete_file_tool_def, delete_file_impl
from tools_rename_file import rename_file_tool_def, rename_file_impl
from tools_create_file import create_file_tool_def, create_file_impl
from tools_template_block import template_block_tool_def, template_block_impl
from tools_web_search import web_search_tool_def, web_search_impl
from tools_todo_write import todo_write_tool_def, todo_write_impl
from tools_aws_api_mcp import aws_api_mcp_tool_def, aws_api_mcp_impl
from tools_aws_billing_mcp import aws_billing_mcp_tool_def, aws_billing_mcp_impl
from tools_playwright_mcp import playwright_mcp_tool_def, playwright_mcp_impl


def build_default_tools() -> list[Tool]:
    return [
        Tool(**read_file_tool_def(), fn=read_file_impl, capabilities={"read_fs"}),
        Tool(**list_files_tool_def(), fn=list_files_impl, capabilities={"read_fs"}),
        Tool(**edit_file_tool_def(), fn=edit_file_impl, capabilities={"write_fs"}),
        Tool(**line_edit_tool_def(), fn=line_edit_impl, capabilities={"write_fs"}),
        Tool(**grep_tool_def(), fn=grep_impl, capabilities={"read_fs"}),
        Tool(
            **run_terminal_cmd_tool_def(),
            fn=run_terminal_cmd_impl,
            capabilities={"exec_shell"},
        ),
        Tool(**glob_file_search_tool_def(), fn=glob_file_search_impl, capabilities={"read_fs"}),
        Tool(
            **codebase_search_tool_def(),
            fn=codebase_search_impl,
            capabilities={"read_fs"},
        ),
        Tool(**apply_patch_tool_def(), fn=apply_patch_impl, capabilities={"write_fs"}),
        Tool(**delete_file_tool_def(), fn=delete_file_impl, capabilities={"write_fs"}),
        Tool(**rename_file_tool_def(), fn=rename_file_impl, capabilities={"write_fs"}),
        Tool(**create_file_tool_def(), fn=create_file_impl, capabilities={"write_fs"}),
        Tool(**template_block_tool_def(), fn=template_block_impl, capabilities={"write_fs"}),
        Tool(**web_search_tool_def(), fn=web_search_impl, capabilities={"network"}),
        Tool(**todo_write_tool_def(), fn=todo_write_impl, capabilities={"write_fs"}),
        Tool(
            **aws_api_mcp_tool_def(),
            fn=aws_api_mcp_impl,
            capabilities={"exec_shell"},
        ),
        Tool(
            **aws_billing_mcp_tool_def(),
            fn=aws_billing_mcp_impl,
            capabilities={"exec_shell"},
        ),
        Tool(
            **playwright_mcp_tool_def(),
            fn=playwright_mcp_impl,
            capabilities={"exec_shell"},
        ),
    ]


def main() -> None:
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Run the interactive Indubitably agent")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--transcript", help="Optional path to append a conversation transcript")
    parser.add_argument(
        "--debug-tool-use",
        dest="debug_tool_use",
        action="store_const",
        const=True,
        help="Enable detailed tool invocation output",
    )
    parser.add_argument(
        "--no-debug-tool-use",
        dest="debug_tool_use",
        action="store_const",
        const=False,
        help="Disable detailed tool invocation output (default)",
    )
    parser.set_defaults(debug_tool_use=False)
    parser.add_argument(
        "--tool-debug-log",
        help="When tool debugging is enabled, append JSONL records of tool invocations to this path",
    )
    args = parser.parse_args()

    run_agent(
        build_default_tools(),
        use_color=not args.no_color,
        transcript_path=args.transcript,
        debug_tool_use=args.debug_tool_use,
        tool_debug_log_path=args.tool_debug_log,
    )


if __name__ == "__main__":
    main()
