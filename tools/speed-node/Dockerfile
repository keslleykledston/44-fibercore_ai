# Nó de teste de banda (Speed Diagnostics, ADR-0038). Imagem mínima, sem root, sem shell de uso.
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /speed-node .

FROM alpine:3.20
RUN addgroup -S app && adduser -S -G app -H -s /sbin/nologin app
COPY --from=build /speed-node /usr/local/bin/speed-node
USER app
ENTRYPOINT ["/usr/local/bin/speed-node"]
