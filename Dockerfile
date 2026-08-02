FROM python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e AS build
WORKDIR /build
COPY . .
RUN python -m pip wheel --no-cache-dir --find-links wheels --wheel-dir /wheels .

FROM python:3.13.11-slim@sha256:2b9c9803c6a287cafa0a8c917211dddd23dcd2016f049690ee5219f5d3f1636e
RUN useradd --create-home --uid 10001 predictor
COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links /wheels f1-predictor && rm -rf /wheels
USER predictor
WORKDIR /home/predictor
ENTRYPOINT ["f1-predictor"]
CMD ["health", "--offline"]
