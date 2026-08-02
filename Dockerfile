FROM python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e AS build
WORKDIR /build
COPY . .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels . \
    "predictor-core @ https://github.com/leonardosovienski/core-predictor/releases/download/v2.1.0/predictor_core-2.1.0-py3-none-any.whl" \
    "predictor-ops @ https://github.com/leonardosovienski/tools-predictor/releases/download/v2.0.1/predictor_ops-2.0.1-py3-none-any.whl"

FROM python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e
RUN useradd --create-home --uid 10001 predictor
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links /wheels f1-predictor && rm -rf /wheels
USER predictor
WORKDIR /home/predictor
ENTRYPOINT ["f1-predictor"]
CMD ["health", "--offline"]
