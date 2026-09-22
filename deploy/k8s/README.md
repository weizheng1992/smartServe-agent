# deploy/k8s —— 场景 E:K8s 部署(设计稿,未实测)

按顺序 apply;PG/Redis 走**云 RDS/云 Redis**(不进集群,见 deploy-scaling.md §4)。

## 前置

1. 集群已装 ingress-nginx + metrics-server(HPA 依赖)
2. 镜像入仓库(占位 `registry.example.com/smartserve/*`,自行替换):
   ```bash
   docker build -f deploy/Dockerfile.gateway -t registry.example.com/smartserve/gateway:1.0 .
   docker build -f deploy/Dockerfile.web      -t registry.example.com/smartserve/web:1.0 .
   docker push registry.example.com/smartserve/gateway:1.0 registry.example.com/smartserve/web:1.0
   ```
3. 生成 JWT 密钥:`openssl rand -hex 32`,填进 `01-secret.yaml`

## 顺序

```bash
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-secret.yaml -f 02-configmap.yaml
kubectl apply -f 40-tei-deployment.yaml          # embedding 先就绪
kubectl apply -f 50-migrate-job.yaml             # 等 Job Completed
kubectl apply -f 10-gateway-deployment.yaml -f 11-gateway-service-hpa.yaml
kubectl apply -f 20-web-deployment.yaml
kubectl apply -f 30-worker-deployment.yaml       # 可选(需 Temporal)
kubectl apply -f 60-ingress.yaml
```

## 注意

- **uploads 多副本**:manifest 用的是 RWO PVC 示例——多副本跨节点会挂载失败,
  换 RWX 存储类(如 CephFS/NAS)或改对象存储(OSS/COS + 预签名 URL)
- **TEI**:单副本足够(embedding 轻量);模型缓存用 emptyDir,Pod 重建重下 ~100MB
- **Temporal**:自托管官方 chart 或云版;`30-worker` 依赖其就绪
- 域名占位 `*.mall.example.com`,Ingress TLS 用 cert-manager 注解补
