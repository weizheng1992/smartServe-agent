import type React from 'react';
import { useState } from 'react';
import { Button, Checkbox, Dialog, DialogContent, DialogHeader, DialogTitle, Input, Label } from 'ui';

export interface CustomerAddress {
  id: string;
  recipientName: string;
  phone: string;
  province?: string;
  city?: string;
  district?: string;
  detailAddress?: string;
  fullAddress: string;
  isDefault?: boolean;
  tag?: string;
}

interface AddressModalProps {
  isOpen: boolean;
  onClose: () => void;
  addresses: CustomerAddress[];
  selectedAddressId?: string;
  onSelectAddress: (address: CustomerAddress) => void;
  onAddAddress: (newAddr: {
    recipientName: string;
    phone: string;
    province: string;
    city: string;
    district: string;
    detailAddress: string;
    isDefault: boolean;
  }) => Promise<void>;
}

export const AddressModal: React.FC<AddressModalProps> = ({
  isOpen,
  onClose,
  addresses,
  selectedAddressId,
  onSelectAddress,
  onAddAddress,
}) => {
  const [showAddForm, setShowAddForm] = useState(false);
  const [saving, setSaving] = useState(false);

  // 表单输入
  const [recipientName, setRecipientName] = useState('');
  const [phone, setPhone] = useState('');
  const [province, setProvince] = useState('北京市');
  const [city, setCity] = useState('北京市');
  const [district, setDistrict] = useState('朝阳区');
  const [detailAddress, setDetailAddress] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleSaveNewAddress = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!recipientName.trim() || !phone.trim() || !detailAddress.trim()) {
      setErrorMsg('请完整填写收货人姓名、联系电话与详细地址');
      return;
    }

    try {
      setSaving(true);
      setErrorMsg('');
      await onAddAddress({
        recipientName: recipientName.trim(),
        phone: phone.trim(),
        province,
        city,
        district,
        detailAddress: detailAddress.trim(),
        isDefault,
      });

      // 重置表单
      setRecipientName('');
      setPhone('');
      setDetailAddress('');
      setIsDefault(false);
      setShowAddForm(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg || '保存地址失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg p-6 max-h-[90vh] flex flex-col">
        <DialogHeader className="pb-3 border-b border-slate-200">
          <DialogTitle className="flex items-center space-x-2 text-lg font-bold text-slate-900">
            <span>📍</span>
            <span>收货地址管理 ({addresses.length})</span>
          </DialogTitle>
        </DialogHeader>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto py-2 space-y-4">
          {errorMsg && (
            <div className="bg-red-50 text-red-700 text-xs p-3 rounded-lg border border-red-200">⚠️ {errorMsg}</div>
          )}

          {!showAddForm ? (
            <>
              {/* 地址列表 */}
              <div className="space-y-3">
                {addresses.map((addr) => {
                  const isSelected = addr.id === selectedAddressId;
                  return (
                    <div
                      key={addr.id}
                      onClick={() => {
                        onSelectAddress(addr);
                        onClose();
                      }}
                      className={`border rounded-xl p-4 cursor-pointer transition-all flex items-start justify-between gap-3 ${
                        isSelected
                          ? 'border-emerald-600 bg-emerald-50/40 ring-2 ring-emerald-500/20'
                          : 'border-slate-200 hover:border-emerald-300 bg-white'
                      }`}
                    >
                      <div className="flex items-start space-x-3">
                        <input
                          type="radio"
                          name="selected_addr"
                          checked={isSelected}
                          onChange={() => {}}
                          className="mt-1 w-4 h-4 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
                        />
                        <div>
                          <div className="flex items-center space-x-2">
                            <span className="font-bold text-sm text-slate-900">{addr.recipientName}</span>
                            <span className="text-xs text-slate-500 font-mono">{addr.phone}</span>
                            {addr.isDefault && (
                              <span className="bg-emerald-100 text-emerald-800 text-[10px] font-semibold px-2 py-0.5 rounded-full">
                                默认
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-slate-600 mt-1.5 leading-relaxed">{addr.fullAddress}</p>
                        </div>
                      </div>

                      <span className="text-xs font-semibold text-emerald-600 shrink-0 mt-1">
                        {isSelected ? '已选定' : '选择'}
                      </span>
                    </div>
                  );
                })}
              </div>

              <Button
                type="button"
                variant="outline"
                onClick={() => setShowAddForm(true)}
                className="w-full py-3 border-2 border-dashed border-emerald-300 hover:border-emerald-500 text-emerald-700 hover:text-emerald-800 font-semibold text-sm bg-emerald-50/50 hover:bg-emerald-50 flex items-center justify-center space-x-2 cursor-pointer mt-2 h-auto"
              >
                <span>➕ 新增收货地址</span>
              </Button>
            </>
          ) : (
            /* 新增地址表单 */
            <form
              onSubmit={handleSaveNewAddress}
              className="space-y-3.5 bg-slate-50 p-4 rounded-xl border border-slate-200"
            >
              <h4 className="text-sm font-bold text-slate-900">填写新收货地址</h4>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs font-medium text-slate-700">收货人姓名 *</Label>
                  <Input
                    type="text"
                    required
                    value={recipientName}
                    onChange={(e) => setRecipientName(e.target.value)}
                    placeholder="如: 张伟"
                    className="text-xs bg-white h-8"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs font-medium text-slate-700">联系电话 *</Label>
                  <Input
                    type="tel"
                    required
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="11位手机号码"
                    className="text-xs bg-white h-8"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs font-medium text-slate-700">省份</Label>
                  <Input
                    type="text"
                    value={province}
                    onChange={(e) => setProvince(e.target.value)}
                    className="text-xs bg-white h-8"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs font-medium text-slate-700">城市</Label>
                  <Input
                    type="text"
                    value={city}
                    onChange={(e) => setCity(e.target.value)}
                    className="text-xs bg-white h-8"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs font-medium text-slate-700">区/县</Label>
                  <Input
                    type="text"
                    value={district}
                    onChange={(e) => setDistrict(e.target.value)}
                    className="text-xs bg-white h-8"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <Label className="text-xs font-medium text-slate-700">详细地址 *</Label>
                <textarea
                  required
                  rows={2}
                  value={detailAddress}
                  onChange={(e) => setDetailAddress(e.target.value)}
                  placeholder="街道门牌信息、小区楼栋与室号"
                  className="w-full text-xs px-3 py-2 border border-slate-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="modal-default-addr"
                  checked={isDefault}
                  onCheckedChange={(checked) => setIsDefault(!!checked)}
                />
                <Label htmlFor="modal-default-addr" className="text-xs text-slate-700 cursor-pointer">
                  设为默认收货地址
                </Label>
              </div>

              <div className="flex gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setShowAddForm(false)}
                  className="flex-1 text-xs"
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={saving}
                  className="flex-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white"
                >
                  {saving ? '正在保存...' : '保存并使用'}
                </Button>
              </div>
            </form>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};
