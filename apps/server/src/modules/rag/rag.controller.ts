import { Body, Controller, Delete, Get, Headers, HttpCode, HttpStatus, Param, Post, Query } from '@nestjs/common';
import { IsNotEmpty, IsObject, IsOptional, IsString } from 'class-validator';
import { RagService } from './rag.service';

export class CreateRagDocDto {
  @IsNotEmpty()
  @IsString()
  chunkText: string;

  @IsOptional()
  @IsString()
  businessId?: string;

  @IsOptional()
  @IsString()
  sourceUrl?: string;

  @IsOptional()
  @IsString()
  contextualSummary?: string;

  @IsOptional()
  @IsObject()
  metadata?: Record<string, unknown>;
}

export class QueryRagDto {
  @IsNotEmpty()
  @IsString()
  query: string;

  @IsOptional()
  @IsString()
  tenantId?: string;
}

@Controller('api/rag')
export class RagController {
  constructor(private readonly ragService: RagService) {}

  @Get('documents')
  async listDocuments(@Query('tenantId') tenantQuery?: string, @Headers('x-tenant-id') tenantHeader?: string) {
    const tenantId = tenantQuery || tenantHeader;
    const data = await this.ragService.getDocuments(tenantId);
    return {
      success: true,
      tenantId: tenantId || 'all',
      total: data.length,
      data,
    };
  }

  @Post('documents')
  @HttpCode(HttpStatus.CREATED)
  async uploadDocument(@Body() body: CreateRagDocDto, @Headers('x-tenant-id') tenantHeader?: string) {
    const businessId = body.businessId || tenantHeader || 'ecommerce';
    const created = await this.ragService.addDocument({
      ...body,
      businessId,
    });
    return {
      success: true,
      data: created,
    };
  }

  @Delete('documents/:id')
  @HttpCode(HttpStatus.OK)
  async deleteDocument(
    @Param('id') id: string,
    @Query('tenantId') tenantQuery?: string,
    @Headers('x-tenant-id') tenantHeader?: string,
  ) {
    const tenantId = tenantQuery || tenantHeader;
    await this.ragService.deleteDocument(id, tenantId);
    return {
      success: true,
      message: `Document ${id} deleted successfully`,
    };
  }

  @Post('query')
  @HttpCode(HttpStatus.OK)
  async queryKnowledge(@Body() body: QueryRagDto, @Headers('x-tenant-id') tenantHeader?: string) {
    const tenantId = body.tenantId || tenantHeader;
    const result = await this.ragService.queryKnowledge(body.query, tenantId);
    return {
      success: true,
      data: result,
    };
  }
}
