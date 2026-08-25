import { Body, Controller, Delete, Get, Headers, HttpCode, HttpStatus, Param, Post, Put, Query } from '@nestjs/common';
import { IsBoolean, IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { GuardrailsService } from './guardrails.service';

export class CreateGuardrailDto {
  @IsNotEmpty()
  @IsString()
  ruleName: string;

  @IsNotEmpty()
  @IsString()
  ruleType: string;

  @IsNotEmpty()
  @IsString()
  pattern: string;

  @IsOptional()
  @IsString()
  action?: string;

  @IsOptional()
  @IsString()
  severity?: string;

  @IsOptional()
  @IsBoolean()
  isEnabled?: boolean;
}

export class UpdateGuardrailDto {
  @IsOptional()
  @IsString()
  ruleName?: string;

  @IsOptional()
  @IsString()
  ruleType?: string;

  @IsOptional()
  @IsString()
  pattern?: string;

  @IsOptional()
  @IsString()
  action?: string;

  @IsOptional()
  @IsString()
  severity?: string;

  @IsOptional()
  @IsBoolean()
  isEnabled?: boolean;
}

@Controller('api/guardrails')
export class GuardrailsController {
  constructor(private readonly guardrailsService: GuardrailsService) {}

  @Get()
  async list(@Query('tenantId') tenantQuery?: string, @Headers('x-tenant-id') tenantHeader?: string) {
    const tenantId = tenantQuery || tenantHeader;
    const data = await this.guardrailsService.getRules(tenantId);
    return {
      success: true,
      tenantId: tenantId || 'all',
      total: data.length,
      data,
    };
  }

  @Post()
  @HttpCode(HttpStatus.CREATED)
  async create(@Body() body: CreateGuardrailDto, @Headers('x-tenant-id') tenantHeader?: string) {
    const data = await this.guardrailsService.createRule(body, tenantHeader);
    return {
      success: true,
      data,
    };
  }

  @Put(':id')
  async update(
    @Param('id') id: string,
    @Body() body: UpdateGuardrailDto,
    @Headers('x-tenant-id') tenantHeader?: string,
  ) {
    const data = await this.guardrailsService.updateRule(id, body, tenantHeader);
    return {
      success: true,
      data,
    };
  }

  @Delete(':id')
  @HttpCode(HttpStatus.OK)
  async delete(@Param('id') id: string, @Headers('x-tenant-id') tenantHeader?: string) {
    await this.guardrailsService.deleteRule(id, tenantHeader);
    return {
      success: true,
      message: `Guardrail rule ${id} deleted successfully`,
    };
  }
}
