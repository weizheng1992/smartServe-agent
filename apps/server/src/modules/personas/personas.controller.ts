import { Body, Controller, Delete, Get, Headers, HttpCode, HttpStatus, Param, Post, Put, Query } from '@nestjs/common';
import { IsNumber, IsOptional, IsString } from 'class-validator';
import { PersonasService } from './personas.service';

export class CreatePersonaDto {
  @IsString()
  userId: string;

  @IsString()
  fact: string;

  @IsOptional()
  @IsString()
  businessId?: string;

  @IsOptional()
  @IsString()
  scope?: string;

  @IsOptional()
  @IsNumber()
  confidence?: number;

  @IsOptional()
  @IsString()
  source?: string;

  @IsOptional()
  @IsString()
  status?: string;
}

export class UpdatePersonaDto {
  @IsOptional()
  @IsString()
  fact?: string;

  @IsOptional()
  @IsNumber()
  confidence?: number;

  @IsOptional()
  @IsString()
  status?: string;
}

@Controller('api/personas')
export class PersonasController {
  constructor(private readonly personasService: PersonasService) {}

  @Get()
  async list(
    @Query('tenantId') tenantQuery?: string,
    @Query('userId') userId?: string,
    @Headers('x-tenant-id') tenantHeader?: string,
  ) {
    const tenantId = tenantQuery || tenantHeader;
    const data = await this.personasService.getFacts(tenantId, userId);
    return {
      success: true,
      tenantId: tenantId || 'all',
      total: data.length,
      data,
    };
  }

  @Post()
  @HttpCode(HttpStatus.CREATED)
  async create(@Body() body: CreatePersonaDto, @Headers('x-tenant-id') tenantHeader?: string) {
    const tenantId = body.businessId || tenantHeader || 'nike';
    const data = await this.personasService.createFact(body, tenantId);
    return {
      success: true,
      data,
    };
  }

  @Put(':id')
  async update(@Param('id') id: string, @Body() body: UpdatePersonaDto, @Headers('x-tenant-id') tenantHeader?: string) {
    const data = await this.personasService.updateFact(id, body, tenantHeader);
    return {
      success: true,
      data,
    };
  }

  @Delete(':id')
  @HttpCode(HttpStatus.OK)
  async delete(@Param('id') id: string, @Headers('x-tenant-id') tenantHeader?: string) {
    await this.personasService.deleteFact(id, tenantHeader);
    return {
      success: true,
      message: `Persona fact ${id} deleted successfully`,
    };
  }
}
