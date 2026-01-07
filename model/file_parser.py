import chromadb 
import pdfplumber
from fastapi import UploadFile
from io import BytesIO
from langchain_text_splitters import RecursiveCharacterTextSplitter
import hashlib
from typing import Dict
from chromadb.config import Settings
from openai import AsyncOpenAI
import os
import warnings


warnings.filterwarnings("ignore", message="Failed to send telemetry event")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

class Chromadb_agent():
    chromadb_client = None,

    def __init__(self):
        self.chromadb_client = chromadb.PersistentClient(
            path="./chromadb_data",
            settings=Settings(anonymized_telemetry=False)
        )
        
    async def index_file(self, session_id: str, filename: str, text: str)->Dict[str, str]:
        collection_name = f"{session_id}_{filename}"
        ##if found the same file in chromadb remove it.
        existing_collections_name =  [each.name for each in self.chromadb_client.list_collections()]
        if collection_name in existing_collections_name:
            self.chromadb_client.delete_collection(collection_name)
        text_spliter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, length_function=len, separators=["\n\n", "\n", ". ", " ", ""])
        chunks = text_spliter.split_text(text)
        formated_chunks = [{"chunk_id": i, "content": chunk, "word_count": len(chunk.split()), "char_count": len(chunk)} for i, chunk in enumerate(chunks)]
        collection = self.chromadb_client.get_or_create_collection(name=collection_name)
        documents, metadata, ids = [], [], []
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

        for chunk_info in formated_chunks:
            documents.append(chunk_info["content"])
            metadata.append({
                "filename": filename,
                "chunk_id": chunk_info["chunk_id"],
                "word_count": chunk_info["word_count"],
                "char_count": chunk_info["char_count"],
                "file_hash": file_hash,
                "session_id": session_id
            })
            ids.append(f"{filename}_{file_hash}_{chunk_info['chunk_id']}")
        
        collection.add(ids=ids, documents=documents, metadatas=metadata)
        ##distance below 1.7 is relevant

        return {
            "filename": filename,
            "total_chunks": len(chunks),
            "total_characters": len(text),
            "collection_name": collection_name,
            "chunks_stored": len(formated_chunks)
        }
    
    def remove_collection_by_filename(self, session_id: str, filename: str)->tuple[str, bool]:
        try:
            self.chromadb_client.delete_collection(f"{session_id}_{filename}")
            return (f"the collection of file {filename} in Session {session_id} has been removed", True)
        except Exception as e:
            return (e, False)
    
    def remove_collection_by_session_id(self, session_id: str)->tuple[str, bool]:
        try:
            collections = self.chromadb_client.list_collections()
            collection_names = list(map(lambda x: x.name, collections))
            matched_collections = [name for name in collection_names if name.startswith(session_id)]
            ##remove the collections which matches session_id
            if matched_collections:
                for each in matched_collections:
                    self.chromadb_client.delete_collection(each)
            else:
                return (f"Session_id {session_id} does not exist", False)
            return (f"Documents associated session_id {session_id} have been removed", True)
        except Exception as e:
            return (e, False)
