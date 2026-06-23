FROM public.ecr.aws/lambda/python:3.12

WORKDIR ${LAMBDA_TASK_ROOT}

RUN pip install --no-cache-dir \
    "fastapi==0.115.0" \
    "mangum>=0.19.0" \
    "yfinance>=0.2.50" \
    "requests==2.32.3" \
    "pydantic==2.9.2" \
    "python-multipart==0.0.12" \
    "anthropic>=0.40.0" \
    "pypdf>=4.0.0" \
    "python-dotenv>=1.0.0" \
    "python-jose[cryptography]>=3.5.0" \
    "boto3>=1.43.3" \
    "bcrypt>=4.0.0"

COPY backend/ ./backend/

CMD ["backend.main.handler"]
