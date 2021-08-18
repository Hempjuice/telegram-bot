FROM python:3.9-buster
COPY bot/requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY bot .
