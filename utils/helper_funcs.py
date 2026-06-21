import os
import aiofiles
from fastapi import File
from model.file_parser import Chromadb_agent
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from model.sqlite import SummaryIndex, AsyncSessionLocal
from sqlalchemy import delete, and_, select
from datetime import datetime
from pathlib import Path
import docker
import time
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from utils.file_content_extractor import file_content_extract
from typing import Type
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from utils.token_counter import get_token_counts
from model.file_upload_models import UploadedFile
from model.session_manager import manager
import asyncio
from model.code_app_models import Code


async def generate_file_summary(file_content: str )->str:
    client = AsyncOpenAI(api_key=os.getenv("api_key"), base_url="https://api.deepseek.com")
    response = await client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "You are a best literature writer, please complete the following task"},
            {"role": "user", "content": f'''
                Plase create a summary of the content of the file in 1 or 2 sentences and make sure the summary will be good enough and NOT too long.
                Please give me the direct summary and the purpose of the document NO OTHERS
                This is the content of the file:
                {file_content}
            '''}
        ],
        stream=False
    )
    return response.choices[0].message.content

async def file_upload_revert_handler(file: File, session_id: str, chromadb_client: Chromadb_agent, db: AsyncSession):
    ##remove residual file
    # if os.path.exists(f"uploads/{session_id}/{file.filename}"):
    #     os.remove(f"uploads/{session_id}/{file.filename}")

    ##remove residual summary index
    delete_statement = delete(SummaryIndex).where(
        and_(
            SummaryIndex.session_id == session_id,
            SummaryIndex.file_name == file.filename
        )
    )
    await db.execute(delete_statement)
    await db.commit()

    ##remove chromadb collection
    chromadb_client.remove_collection_by_filename(session_id=session_id, filename=file.filename)


async def file_upload_handler(file: File, session_id: str, chromadb_client: Chromadb_agent)->UploadedFile:
    file_path = Path((f"coding_space/{session_id}/{file.filename}"))
    MAX_INDEX_THRESHOLD = 320_000
    os.makedirs(file_path.parent, exist_ok=True)
    try:
        ##save the file into the directory
        async with aiofiles.open(file_path, "wb") as buffer:
            content = await file.read()
            await buffer.write(content)

        ##content extract
        file_content_result = await file_content_extract(file_path=file_path)
        if file_content_result[0]:
            num_tokens = await asyncio.to_thread(get_token_counts, file_content_result[1])
            if num_tokens < MAX_INDEX_THRESHOLD:
                ##indexing the uploads
                await chromadb_client.index_file(session_id=session_id,  filename=file.filename, text=file_content_result[1])
                ##generate summary and save it into sqlite
                summary = await generate_file_summary(file_content=file_content_result[1])

                ##each corutines must use a different db session
                async with AsyncSessionLocal() as db:
                    ##upsert ops the summary index record
                    result = await db.execute(
                        select(SummaryIndex).where(
                            and_(
                                SummaryIndex.session_id == session_id,
                                SummaryIndex.file_name == file.filename
                            )
                        )
                    )
                    existing_summary = result.scalar_one_or_none()
                    if existing_summary:
                        existing_summary.summary = summary
                        existing_summary.updated_at = datetime.now()
                    else:
                        new_summary = SummaryIndex(
                            session_id=session_id,
                            file_name=file.filename,
                            summary=summary,
                            updated_at=datetime.now()
                        )
                        db.add(new_summary)
                    await db.commit()
                return UploadedFile(
                    file_name=file.filename, 
                    estimated_tokens=num_tokens, 
                    process_method="file_search", 
                    result=True
                )
        return UploadedFile(
            file_name=file.filename, 
            estimated_tokens=0, 
            process_method="coding", 
            result=False
        )
    except Exception as e:
            await file_upload_revert_handler(file=file, session_id=session_id, chromadb_client=chromadb_client, db=db)
            return UploadedFile(
                file_name=file.filename, 
                estimated_tokens=0, 
                process_method="coding", 
                result=False
            )

def get_uploaded_file_from_session(session_id: str)->str | None:
    '''
    getting the file upload status from the session, only getting once
    '''
    session = manager.get_session(thread_id=session_id)
    if session.get("file_upload", []): ##if there is any existing file upload
        file_upload_summary = ""
        for each_file in session.get("file_upload"):
            process_method = "writing code app to process" if each_file.process_method == "coding" else "using file search app to search"
            file_upload_summary += f"File name: {each_file.file_name}, MUST ROUTE TO: {process_method} agent to process"
        manager.update_session(thread_id=session_id, updates={**session, "file_upload": []}) ## remove upload record once read
        return file_upload_summary
    else:
        return None
    
    

async def summary_fetcher(session_id: str)-> tuple[bool, str | None]:
    async with AsyncSessionLocal() as db:
        select_statement = select(SummaryIndex).where(SummaryIndex.session_id == session_id)
        summaries = await db.execute(select_statement)
        existing_summaries = summaries.scalars().all()
        if existing_summaries:
            converted_summaries = [str({"file_name": each.file_name, "summary": each.summary }) for each in existing_summaries]
            return (True, "\n".join(converted_summaries))
        else:
            return (False, None)
        
def run_docker_commands(thread_id: str, exe_cmds: list[str], code_files: list[Code])->tuple[bool, str]:
    '''
    checking if container with thread_id already running, if not run it
    then running the commands in loop
    '''
    error_result = None
    host_path = os.path.abspath(f"coding_space/{thread_id}")
    if code_files: ##writing code into files
        for each in code_files:
            file_name = each.file_name.strip()
            if not file_name or file_name in [".", ".."]:
                continue
            with open(f"{host_path}/{each.file_name}", "w") as f:
                f.write(each.code_text)
    results = []
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": f"^{thread_id}"})
        if not containers:
            container = client.containers.run(
                image="python:3.11.15-trixie",
                name=thread_id,
                volumes={
                    host_path: {"bind": "/usr/src/app", "mode": "rw"}
                },
                command="tail -f /dev/null",
                detach=True
            )
            for _ in range(10):
                container.reload()
                if container.status == "running":
                    break
                time.sleep(0.5)
        else:
            if containers[0].status != "running":
                containers[0].start()
                containers[0].reload()
            container = containers[0]
        for cmd in exe_cmds:
            exit_code, output = container.exec_run(cmd, workdir="/usr/src/app")
            if exit_code != 0:
                error_result = f"cmd: {cmd}, error: {output.decode('utf-8').strip()}, exit_code: {exit_code}"
                return (False, ";".join(results + [error_result]))
            results.append(f"cmd: {cmd} running successfully, output is \n{'None' if output is None else output.decode('utf-8').strip()}, exit_code: {exit_code}")
        return (True, ";".join(results))
    
    except Exception as e:
        return (False, ";".join(results + [error_result]))


async def safely_ainvoke(
        *, 
        model: BaseChatModel, 
        message_sequence: list[BaseMessage], 
        null_response_model_switch: bool = True,
        circuit_break_threshold: int = 3,
        response_schema: Type[BaseModel] = None ##response schema type
    )->tuple[bool, object]:
    '''
    async invoke response with data type validate and any other exception graceful handle,
    if null_response_model_switch is True if there are 3 consecvtive null response then switch model
    '''
    NULL_RESPONSE_ERROR = "LLM error: Reponse is None...Please retry"
    if null_response_model_switch:
        pos = 0
        consecutive_counter = 0
        consecutive_group = 0
        while pos < len(message_sequence):
            if NULL_RESPONSE_ERROR in message_sequence[pos].content:
                consecutive_counter += 1
                if consecutive_counter == circuit_break_threshold:
                    consecutive_group += 1
                    consecutive_counter = 0
                    pos += 1
                else:
                    pos += 2
            else:
                consecutive_counter = 0
                pos += 1

        if consecutive_group % 2:
            ##model failover
            failover_model = ChatOpenAI(model="gpt-4o", api_key=os.getenv("openai_api_key"), top_p=0.1, temperature=0)
            print("Failover to gpt-4o")
            if response_schema:
                model = failover_model.with_structured_output(response_schema)
        else:
            print("Using deepseek")

    try:
        response = await model.ainvoke(message_sequence)
        if response is None:
            raise ValueError(NULL_RESPONSE_ERROR)
    except Exception as e:
        return (False, str(e))
    return (True, response)