import { Body, Controller, Get, HttpCode, HttpStatus, Post } from '@nestjs/common';
import { IsNotEmpty, IsOptional, IsString } from 'class-validator';
import { EvalsService } from './evals.service';

export class TriggerEvalDto {
  @IsNotEmpty()
  @IsString()
  datasetName: string;

  @IsOptional()
  @IsString()
  runName?: string;
}

@Controller('api/evals')
export class EvalsController {
  constructor(private readonly evalsService: EvalsService) {}

  @Get('results')
  async getResults() {
    const data = await this.evalsService.getEvalResults();
    return {
      success: true,
      total: data.length,
      data,
    };
  }

  @Post('run')
  @HttpCode(HttpStatus.OK)
  async triggerRun(@Body() body: TriggerEvalDto) {
    const data = await this.evalsService.triggerRun(body.datasetName, body.runName);
    return {
      success: true,
      data,
    };
  }
}
