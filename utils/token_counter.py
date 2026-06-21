import tiktoken

def get_token_counts(content: str)->int:
    '''
    count the number of token given by the content
    '''
    enc = tiktoken.get_encoding("cl100k_base")
    token_count = len(enc.encode(content))
    return token_count