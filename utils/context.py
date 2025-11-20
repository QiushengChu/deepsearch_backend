from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from typing import Sequence
from model.prompt_cache_model import prompt_cache

def conext_purifier(state_messages: Sequence[BaseMessage])->Sequence[BaseMessage]:
    '''
    This function is for making a copy of the orignal message states and return a purified state messages without ToolCalls and ToolMessage
    '''
    converted_messages = []
    for message in state_messages:
        if isinstance(message, ToolMessage):
            converted_messages.append(
                HumanMessage(content=message.content)
            )
        elif isinstance(message, AIMessage):
            ##if AI message has tool calls, remove the tool related content, in case AI decides to call the tool belonging to other agents
            if hasattr(message, 'tool_calls') and message.tool_calls:
                if message.content:
                    converted_messages.append(AIMessage(content=message.content))
            else:
                converted_messages.append(AIMessage(content=message.content))
        else:
            converted_messages.append(message)
    return converted_messages

def prompt_fetcher_from_cache(thread_id: str)->list[HumanMessage]:
    prompt_list = prompt_cache.session[thread_id]
    if prompt_list:
        human_message_list = [HumanMessage(content=each['message']) for each in prompt_list]
        return human_message_list
    return []
    
    
def prompt_remover_from_cache(thread_id: str)->None:
    prompt_cache.session[thread_id] = []