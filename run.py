from agent import run_agent, Tool
from tools_read import read_file_tool_def, read_file_impl
from tools_list import list_files_tool_def, list_files_impl
from tools_edit import edit_file_tool_def, edit_file_impl
from tools_grep import grep_tool_def, grep_impl
from tools_run_terminal_cmd import run_terminal_cmd_tool_def, run_terminal_cmd_impl
from tools_glob_file_search import glob_file_search_tool_def, glob_file_search_impl
from tools_codebase_search import codebase_search_tool_def, codebase_search_impl
from tools_apply_patch import apply_patch_tool_def, apply_patch_impl
from tools_delete_file import delete_file_tool_def, delete_file_impl
from tools_web_search import web_search_tool_def, web_search_impl
from tools_todo_write import todo_write_tool_def, todo_write_impl


if __name__ == "__main__":
    tools = [
        Tool(**read_file_tool_def(), fn=read_file_impl),
        Tool(**list_files_tool_def(), fn=list_files_impl),
        Tool(**edit_file_tool_def(), fn=edit_file_impl),
        Tool(**grep_tool_def(), fn=grep_impl),
        Tool(**run_terminal_cmd_tool_def(), fn=run_terminal_cmd_impl),
        Tool(**glob_file_search_tool_def(), fn=glob_file_search_impl),
        Tool(**codebase_search_tool_def(), fn=codebase_search_impl),
        Tool(**apply_patch_tool_def(), fn=apply_patch_impl),
        Tool(**delete_file_tool_def(), fn=delete_file_impl),
        Tool(**web_search_tool_def(), fn=web_search_impl),
        Tool(**todo_write_tool_def(), fn=todo_write_impl),
    ]
    run_agent(tools)


