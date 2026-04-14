# FAIR Data Station (FAIR-DS) — reproducible image built from the public distribution JAR.
# Default download matches the URL used in the main README; override at build time if needed.
FROM eclipse-temurin:17-jre-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG FAIRDS_DOWNLOAD_URL=http://download.systemsbiology.nl/unlock/fairds-latest.jar
RUN curl -fL -o /app/fairds.jar "${FAIRDS_DOWNLOAD_URL}"

EXPOSE 8083

ENV JAVA_TOOL_OPTIONS="-Xmx2g"

# Spring Boot-style port flag (FAIR-DS ships as an executable JAR)
CMD ["java", "-jar", "/app/fairds.jar", "--server.port=8083"]
