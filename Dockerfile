FROM python:3.10-slim

# Install system dependencies (LaTeX, Redis tools, WeasyPrint deps)
RUN apt-get update && apt-get install -y \
    texlive-xetex \
    texlive-fonts-recommended \
    texlive-latex-extra \
    pandoc \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN cd front-end && npm install && npm run build

EXPOSE 5005