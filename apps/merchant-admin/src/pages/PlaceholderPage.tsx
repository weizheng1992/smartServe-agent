// 六 tab 平移(19-D1):订单/商品/客服等现有页面整体迁移属后续搬运票;
// 本页保持菜单无死链(有路由即有内容说明)。
export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-2xl rounded-xl border border-dashed border-zinc-300 bg-white p-8 text-center">
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-2 text-xs leading-5 text-zinc-400">
        现有六 tab 平移位(spec 19-D1);悬浮助手已可用(右下角 🤖),
        选中数据 → 提问的 PageContext 交互随列表页迁移接入。
      </div>
    </div>
  );
}
