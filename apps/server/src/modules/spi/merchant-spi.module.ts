import { Module } from "@nestjs/common";
import {
  MerchantSpiController,
  MerchantSpiService,
} from "./merchant-spi.controller";

@Module({
  controllers: [MerchantSpiController],
  providers: [MerchantSpiService],
  exports: [MerchantSpiService],
})
export class MerchantSpiModule {}
