import { Controller, Get } from '@nestjs/common';

@Controller('api/health')
export class HealthController {
  @Get()
  getHealth() {
    return {
      status: 'ok',
      service: 'agent-gateway-server',
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
    };
  }
}
