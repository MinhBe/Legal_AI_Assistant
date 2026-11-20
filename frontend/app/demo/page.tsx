import Chat from "@/components/Chat";

/* /demo: không cần đăng nhập; 3 tình huống mẫu bấm là chạy, có bản ghi sẵn dự phòng. */
export const metadata = { title: "LawVN – Demo" };

export default function DemoPage() {
  return <Chat demo />;
}
