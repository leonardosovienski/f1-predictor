FROM python:3.13.14-alpine3.24@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0 AS build
RUN apk add --no-cache build-base
WORKDIR /build
COPY . .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels . \
    "predictor-core @ https://github.com/leonardosovienski/core-predictor/releases/download/v2.2.0/predictor_core-2.2.0-py3-none-any.whl" \
    "predictor-ops @ https://github.com/leonardosovienski/tools-predictor/releases/download/v3.0.0/predictor_ops-3.0.0-py3-none-any.whl"

FROM python:3.13.14-alpine3.24@sha256:399babc8b49529dabfd9c922f2b5eea81d611e4512e3ed250d75bd2e7683f4b0
RUN adduser -S -D -u 10001 -h /home/predictor predictor
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links /wheels f1-predictor && rm -rf /wheels
USER predictor
WORKDIR /home/predictor
ENTRYPOINT ["f1-predictor"]
CMD ["health", "--offline"]
