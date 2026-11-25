# 加载随包 SDK

`scripts/sdk_bootstrap.py` 按本包的 `assets/sdk/bundle.json` 校验 wheel 并加载 `auto_modeling`。可以在 SimBot 提供的 Skill 资源路径下执行；若执行器从别处启动，把入口示例中的 `Path("scripts")` 换为该资源路径下的 `scripts`。本包不依赖开发仓库。

需要诊断时，从 Skill 根目录执行：

```sh
python -B -c "import sys; sys.path.insert(0, 'scripts'); from sdk_bootstrap import doctor; print(doctor())"
```

已验证组合为 Python 3.12、官方 `cloudpss==5.0.10` 和 `mirascript==0.1.103`。本包携带扩展 wheel。官方 SDK 等第三方依赖由运行环境提供；如果缺失且环境支持安装，可用 `python scripts/setup_sdk.py --venv <任务环境路径>` 安装到独立环境，再使用该环境的 Python。安装依赖需要可用的包源。

打开云端项目时使用平台注入的 CloudPSS 凭据。如环境显式提供配置文件，可从本包的 `configure_cloudpss` 导入同名函数，在首次请求前传入配置路径。离线模型和本地定义缓存可直接使用。处理认证错误时报告缺少的配置项，凭据值留在运行环境内。
