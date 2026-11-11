# -*- coding: utf-8 -*-
"""core: 基础设施层。

- config:    全项目配置（.env 加载）
- llm:       LLM 多供应商路由 + 降级容灾（M6 深化）
- logging:   统一日志 + 脱敏
- security:  密码哈希 / 注入防护 / 内容校验（M6 深化）
"""
