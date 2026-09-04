import React, { createContext, useContext, useState } from 'react';

export interface MerchantUser {
  id: string; // e.g. "CUST-8801"
  name: string; // e.g. "张伟"
  phone: string; // e.g. "13800138000"
  tier: string; // e.g. "黑金SVIP" | "白金会员" | "黄金会员" | "注册用户"
  avatar?: string;
  defaultAddress: string;
}

export const PRESET_USERS: MerchantUser[] = [
  {
    id: 'CUST-8801',
    name: '张伟',
    phone: '13800138000',
    tier: '黑金SVIP',
    defaultAddress: '北京市海淀区中关村南大街1号院8号楼1201室',
  },
  {
    id: 'CUST-8802',
    name: '李娜',
    phone: '13900139000',
    tier: '白金会员',
    defaultAddress: '上海市浦东新区陆家嘴环路1000号恒生银行大厦22层',
  },
  {
    id: 'CUST-8803',
    name: '王强',
    phone: '13700137000',
    tier: '注册会员',
    defaultAddress: '广东省深圳市南山区粤海街道科技园南区高新南一道8号',
  },
];

interface UserContextValue {
  user: MerchantUser;
  switchUser: (user: MerchantUser) => void;
  loginUser: (custom: Partial<MerchantUser>) => void;
  presetUsers: MerchantUser[];
}

const UserContext = createContext<UserContextValue | null>(null);

const STORAGE_KEY = 'aurora_merchant_current_user';

export function UserProvider({ children }: { children: React.ReactNode }) {
  // 从 localStorage 同步初始化当前用户:若延迟到 useEffect 再恢复,首帧会以预设
  // 用户(张伟/CUST-8801)渲染,聊天挂件等子组件将用错误身份发起请求,并把该
  // 预设用户的活跃线程劫持进当前视图(身份竞态)。
  const [user, setUser] = useState<MerchantUser>(() => {
    try {
      const saved = typeof window !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null;
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed?.id && parsed?.name) {
          return parsed;
        }
      }
    } catch {
      // ignore
    }
    return PRESET_USERS[0];
  });

  const switchUser = (newUser: MerchantUser) => {
    setUser(newUser);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(newUser));
    } catch {
      // ignore
    }
  };

  const loginUser = (custom: Partial<MerchantUser>) => {
    const updated: MerchantUser = {
      id: custom.id || `CUST-${Math.floor(1000 + Math.random() * 9000)}`,
      name: custom.name || '极光顾客',
      phone: custom.phone || '13800138000',
      tier: custom.tier || '注册会员',
      defaultAddress: custom.defaultAddress || '北京市朝阳区三里屯太古里北区B1层',
    };
    switchUser(updated);
  };

  return (
    <UserContext.Provider
      value={{
        user,
        switchUser,
        loginUser,
        presetUsers: PRESET_USERS,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useCurrentUser() {
  const context = useContext(UserContext);
  if (!context) {
    return {
      user: PRESET_USERS[0],
      switchUser: () => {},
      loginUser: () => {},
      presetUsers: PRESET_USERS,
    };
  }
  return context;
}
