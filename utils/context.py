from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from typing import Sequence
from model.prompt_cache_model import prompt_cache

def context_purifier(state_messages: Sequence[BaseMessage])->Sequence[BaseMessage]:
    '''
    This function is for making a copy of the original message states and return a purified state messages without ToolCalls and ToolMessage
    '''
    converted_messages = []
    
    for message in state_messages:
        if isinstance(message, ToolMessage):
            # ToolMessage → HumanMessage
            converted_messages.append(
                HumanMessage(content=message.content)
            )
        elif isinstance(message, AIMessage):
            has_tool_calls = (hasattr(message, 'tool_calls') and message.tool_calls and len(message.tool_calls) > 0)
            
            if has_tool_calls: ##with tool calls
                if message.content:
                    # with content, save content
                    converted_messages.append(AIMessage(content=message.content, addtional_kwargs=message.additional_kwargs, usage_metadata=message.usage_metadata))
                else:
                    # not content，use tool_calls to create content
                    tool_summary = ", ".join([
                        f"{tc.get('name', 'tool')}({list(tc.get('args', {}).keys())})" 
                        for tc in message.tool_calls
                    ])
                    converted_messages.append(AIMessage(content=f"[Tool calls: {tool_summary}]", addtional_kwargs=message.additional_kwargs, usage_metadata=message.usage_metadata))
            else:
                converted_messages.append(message)
        else:
            converted_messages.append(message)
    
    return converted_messages

def prompt_fetcher_from_cache(thread_id: str)->list[HumanMessage]:
    prompt_list = prompt_cache.session[thread_id]
    if prompt_list:
        human_message_list = [HumanMessage(
            content=each['message'],
            additional_kwargs={
                "file_names": each.file_names
            }
        ) for each in prompt_list]
        return human_message_list
    return []
    
    
def prompt_remover_from_cache(thread_id: str)->None:
    prompt_cache.session[thread_id] = []