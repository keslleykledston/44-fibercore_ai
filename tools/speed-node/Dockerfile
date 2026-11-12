# Nó de teste de banda (Speed Diagnostics, ADR-0038). Imagem mínima, sem root, sem shell de uso.
FROM golang:1.22-alpine@sha256:1699c10032ca2582ec89a24a1312d986a3f094aed3d5c1147b19880afe40e052 AS build
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /speed-node .

FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
RUN addgroup -S app && adduser -S -G app -H -s /sbin/nologin app
COPY --from=build /speed-node /usr/local/bin/speed-node
USER app
ENTRYPOINT ["/usr/local/bin/speed-node"]
