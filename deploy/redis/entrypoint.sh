#!/bin/sh
# Builds the Redis ACL file from Docker secrets, then starts Redis.
# Each service gets its own user restricted to the keys/channels it needs
# (see backend/captions/rkeys.py). The default user is disabled.
set -eu

pw() { cat "/run/secrets/$1"; }

ACL=/tmp/users.acl
umask 077
cat > "$ACL" <<EOF
user default off
user worker on >$(pw redis_worker_password) ~* &* +@all -@admin -@dangerous +info
user admin on >$(pw redis_admin_password) ~* &* +@read +@write +@pubsub +@connection +@keyspace +@transaction -@admin -@dangerous -flushall -flushdb -keys
user ingest on >$(pw redis_ingest_password) resetchannels &ingest:* ~audio:* ~campus:live:* -@all +@connection +xadd +hset +hgetall +expire +del +lpush +ltrim +get +subscribe +unsubscribe
user public on >$(pw redis_public_password) resetchannels &cap:* &status:* ~public:* ~capbuf:* ~viewers:* -@all +@connection +get +lrange +hset +expire +del +psubscribe +punsubscribe
user localaudio on >$(pw redis_localaudio_password) resetchannels ~audio:* ~localaudio:* ~campus:live:* -@all +@connection +xadd +hset +hdel +expire +lpush +ltrim +get +set
EOF

exec redis-server \
  --aclfile "$ACL" \
  --save "" \
  --appendonly no \
  --maxmemory 256mb \
  --maxmemory-policy volatile-lru \
  --protected-mode yes \
  --rename-command FLUSHALL "" \
  --rename-command CONFIG ""
