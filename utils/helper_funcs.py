import os
import aiofiles
from fastapi import File
from model.file_parser import Chromadb_agent
from sqlalchemy.ext.asyncio import AsyncSession
from openai import AsyncOpenAI
from fastapi import UploadFile
from io import BytesIO
import pdfplumber
from model.sqlite import SummaryIndex, AsyncSessionLocal
from sqlalchemy import delete, and_, select
from datetime import datetime
import logging


async def extract_content(file: UploadFile)->str:
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    await file.seek(0) ##reset file reader position to 0
    content = await file.read()
    pdf_bytes = BytesIO(content)
    text = ""
    ##extract the text and chunk
    with pdfplumber.open(pdf_bytes) as pdf:
        for idx, page in enumerate(pdf.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            except Exception as page_error:
                print(f"Error extracting text from page {idx + 1}: {page_error}")
                continue

    return text


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
    if os.path.exists(f"uploads/{session_id}/{file.filename}"):
        os.remove(f"uploads/{session_id}/{file.filename}")

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


async def file_upload_handler(file: File, session_id: str, chromadb_client: Chromadb_agent)->dict[str, str|bool]:
    file_path = os.path.join(f"uploads/{session_id}/{file.filename}")
    try:
        ##save the file into the directory
        async with aiofiles.open(file_path, "wb") as buffer:
            content = await file.read()
            await buffer.write(content)

        ##content extract
        file_content = await extract_content(file=file)
        ##indexing the uploads
        await chromadb_client.index_file(session_id=session_id,  filename=file.filename, text=file_content)
        ##generate summary and save it into sqlite
        summary = await generate_file_summary(file_content=file_content)


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
    except Exception as e:
            ##fallback to remove all the associated data
            await file_upload_revert_handler(file=file, session_id=session_id, chromadb_client=chromadb_client, db=db)
            return {"name": file.filename, "result": False}
    return {"name": file.filename, "result": True}


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