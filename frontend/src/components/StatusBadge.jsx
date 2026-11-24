export default function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="dot" />
      {status}
    </span>
  )
}
