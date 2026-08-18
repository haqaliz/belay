FROM python:3.12-slim
COPY dist/belay_harness-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/belay_harness-*.whl \
    && rm /tmp/belay_harness-*.whl
RUN adduser --disabled-password --uid 1000 --gecos "" belay
WORKDIR /workspace
USER belay
ENTRYPOINT ["belay"]
